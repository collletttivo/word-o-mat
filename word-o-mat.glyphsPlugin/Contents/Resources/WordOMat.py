# coding=utf-8
#
"""
word-o-mat is a RoboFont extension that generates test words for type testing, sketching etc.
I assume no responsibility for inappropriate words found on those lists and rendered by this script :)

v2.2.4 / Nina Stössinger / 31.05.2015
Thanks to Just van Rossum, Frederik Berlaen, Tobias Frere-Jones, Joancarles Casasín, James Edmondson
Also to Roberto Arista, Sindre Bremnes, Mathieu Christe/David Hodgetts for help with wordlists

ported by Georg Seifert 11.12.2013
update to version 2.2.5, 19.12.2017
"""
from __future__ import print_function

import os

import codecs
import random
import re
import webbrowser

from lib import addObserver, removeObserver, CurrentFont, registerExtensionDefaults, getExtensionDefault, setExtensionDefault, ExtensionBundle, OpenSpaceCenter, AllFonts, AccordionView
# from vanilla.dialogs import getFile # open dialog from the vanilla version used in Glyphs 2 is not working in 10.15 (and above) any more. So if we drop Glyphs 2 support, this can be reverted
from GlyphsApp import GetOpenFile, Message
from vanilla import Window, Button, PopUpButton, SegmentedButton, Group, Box, TextBox, EditText, CheckBox, ComboBox

from random import choice
import wordcheck
warned = False


class WordomatWindow:

    def writingSystemCallback(self, sender):
        """Called when the writing system selection changes."""
        selectedWS = sender.getItem()
        self.updateLanguagePopUp(selectedWS)

    def updateLanguagePopUp(self, writingSystem):
        """Update the language pop-up based on the selected writing system."""
        languages = self.languagesByWS.get(writingSystem, [])
        self.g1.language.setItems(languages)
        # Optionally, select the first language if available
        if languages:
            self.g1.language.set(0)

    def languageCallback(self, sender):
        """Called when the language selection changes (if needed for future use)."""
        pass

    def __init__(self):
        """Initialize word-o-mat UI, open the window."""
        # load preferences and dictionaries
        self.loadPrefs()
        self.loadDictionaries()

        # Observers for font events
        addObserver(self, lambda: self.g1.base.enable(True), "fontDidOpen")
        addObserver(self, "fontClosed", "fontWillClose")

        # Build the window and UI
        self.w = Window((250, 430), 'word-o-mat')
        padd, bPadd = 12, 3
        groupW = 250 - 2 * padd  # group width

        # Increase the height of the basic settings group to accommodate all elements.
        self.g1 = Group((padd, 2, groupW, 100))

        # Top line fields (word count, min length, max length)
        topLineFields = {
            "wordCount": [0, 32, self.wordCount, 20],
            "minLength": [110, 28, self.minLength, 3],
            "maxLength": [147, 28, self.maxLength, 10],
        }
        topLineLabels = {
            "wcText": [35, 78, 'words with', 'left'],
            "lenTextTwo": [135, 15, u'–', 'center'],
            "lenTextThree": [178, -0, 'letters', 'left'],
        }

        for label, values in topLineFields.items():
            setattr(self.g1, label, EditText((values[0], 0, values[1], 22), text=values[2], placeholder=str(values[3])))

        for label, values in topLineLabels.items():
            setattr(self.g1, label, TextBox((values[0], 3, values[1], 22), text=values[2], alignment=values[3]))

        # --- New UI Elements for Writing System and Language selection ---
        self.g1.writingSystem = PopUpButton((0, 29, 110, 20),
                                            self.writingSystems,
                                            callback=self.writingSystemCallback,
                                            sizeStyle="small")
        self.g1.language = PopUpButton((116, 29, 110, 20),
                                       [],
                                       callback=self.languageCallback,
                                       sizeStyle="small")
        # Set initial selection: if any writing systems exist, select the first and update languages accordingly.
        if self.writingSystems:
            self.g1.writingSystem.set(0)
            self.updateLanguagePopUp(self.writingSystems[0])

        ransom_note = ransom("ransom note")
        caseList = ["Keep case", "make lowercase", "Capitalize", "ALL CAPS", ransom_note]
        self.g1.case = PopUpButton((0, 52, groupW, 20), caseList, sizeStyle="small")
        self.g1.case.set(self.case)

        charsetList = [
            "Use any characters",
            "Use characters in current font",
            "Use only selected glyphs",
        ]
        self.g1.base = PopUpButton((0, 75, groupW, 20), charsetList, sizeStyle="small")
        if not CurrentFont():
            self.g1.base.set(0)  # Use any characters
            self.g1.base.enable(False)  # Disable selection if no font is open
        else:
            self.g1.base.set(self.limitToCharset)

        # Panel 2 - Match letters
        self.g2 = Group((0, 2, 250, 172))

        # Match mode selection
        matchBtnItems = [
            dict(width=40, title="Text", enabled=True),
            dict(width=120, title="GREP pattern match", enabled=True)
        ]
        self.g2.matchMode = SegmentedButton((40, 4, -0, 20), matchBtnItems, callback=self.switchMatchModeCallback,
                                            sizeStyle="small")
        rePanelOn = 1 if self.matchMode == "grep" else 0
        self.g2.matchMode.set(rePanelOn)

        # Text/List match mode panel
        self.g2.textMode = Box((padd, 29, -padd, 133))
        labelY = [2, 42]
        labelText = ["Require these letters in each word:", "Require one per group in each word:"]
        for i in range(2):
            setattr(self.g2.textMode, "reqLabel%s" % i,
                    TextBox((bPadd, labelY[i], -bPadd, 22), labelText[i], sizeStyle="small"))
        self.g2.textMode.mustLettersBox = EditText((bPadd + 2, 18, -bPadd, 19), text=", ".join(self.requiredLetters),
                                                   sizeStyle="small")
        y2 = 36
        attrNameTemplate = "group%sbox"
        for i in range(3):
            j = i + 1
            y2 += 21
            optionsList = ["%s: %s" % (key, ", ".join(value)) for key, value in self.groupPresets]
            if len(self.requiredGroups[i]) > 0 and self.requiredGroups[i][0] != "":
                optionsList.insert(0, "Recent: " + ", ".join(self.requiredGroups[i]))
            attrName = attrNameTemplate % j
            setattr(self.g2.textMode, attrName, ComboBox((bPadd + 2, y2, -bPadd, 19), optionsList, sizeStyle="small"))
        groupBoxes = [self.g2.textMode.group1box, self.g2.textMode.group2box, self.g2.textMode.group3box]
        for i in range(3):
            if len(self.requiredGroups[i]) > 0 and self.requiredGroups[i][0] != "":
                groupBoxes[i].set(", ".join(self.requiredGroups[i]))

        # GREP match mode panel
        self.g2.grepMode = Box((padd, 29, -padd, 133))
        self.g2.grepMode.label = TextBox((bPadd, 2, -bPadd, 22), "Regular expression to match:", sizeStyle="small")
        self.g2.grepMode.grepBox = EditText((bPadd + 2, 18, -bPadd, 19), text=self.matchPattern, sizeStyle="small")
        splainstring = u"This uses Python’s internal re parser.\nExamples:\nf[bhkl] = words with f followed by b, h, k, or l\n.+p.+ = words with p inside them\n^t.*n{2}$ = words starting with t, ending in nn"
        self.g2.grepMode.explainer = TextBox((bPadd, 42, -bPadd, 80), splainstring, sizeStyle="mini")
        self.g2.grepMode.refButton = Button((bPadd, 108, -bPadd, 14), "go to syntax reference", sizeStyle="mini",
                                            callback=self.loadREReference)
        self.g2.grepMode.show(0)
        self.toggleMatchModeFields()  # Switch to text or grep panel depending on matchMode

        # Panel 3 - Options
        self.g3 = Group((padd, 8, groupW, 48))
        self.g3.checkbox0 = CheckBox((bPadd, 0, -bPadd, 18), "No repeating characters per word", sizeStyle="small",
                                     value=self.banRepetitions)
        self.g3.listOutput = CheckBox((bPadd, 20, -bPadd, 18), "Output as list sorted by width", sizeStyle="small")

        accItems = [
            dict(label="Basic settings", view=self.g1, size=105, collapsed=False, canResize=False),
            dict(label="Specify required letters", view=self.g2, size=173, collapsed=False, canResize=False),
            dict(label="Options", view=self.g3, size=48, collapsed=False, canResize=False)
        ]
        self.w.panel1 = Group((0, 0, 250, -35))
        self.w.panel1.accView = AccordionView((0, 0, -0, -0), accItems)

        self.w.submit = Button((padd, -32, -padd, 22), 'make words!', callback=self.makeWords)
        self.w.bind("close", self.windowClose)
        self.w.setDefaultButton(self.w.submit)
        self.w.open()

    def loadPrefs(self):
        """Load the saved preferences into the program."""
        self.requiredLetters = []
        self.requiredGroups = [[], [], []]
        self.banRepetitions = False

        # preset character groups
        self.groupPresets = [
            ["[lc] Ascenders", ["b", "f", "h", "k", "l"]],
            ["[lc] Descenders", ["g", "j", "p", "q", "y"]],
            ["[lc] Ball-and-Stick", ["b", "d", "p", "q"]],
            ["[lc] Arches", ["n", "m", "h", "u"]],
            ["[lc] Diagonals", ["v", "w", "x", "y"]]
        ]

        # define initial values
        initialDefaults = {
            "com.ninastoessinger.word-o-mat.wordCount": 20,
            "com.ninastoessinger.word-o-mat.minLength": 3,
            "com.ninastoessinger.word-o-mat.maxLength": 15,
            "com.ninastoessinger.word-o-mat.case": 0,
            "com.ninastoessinger.word-o-mat.limitToCharset": 1,
            "com.ninastoessinger.word-o-mat.source": 0,
            "com.ninastoessinger.word-o-mat.matchMode": "text",
            "com.ninastoessinger.word-o-mat.matchPattern": "",
            "com.ninastoessinger.word-o-mat.markColor": "None",
        }
        registerExtensionDefaults(initialDefaults)

        # load prefs into variables/properties
        prefsToLoad = {
            "wordCount": "com.ninastoessinger.word-o-mat.wordCount",
            "minLength": "com.ninastoessinger.word-o-mat.minLength",
            "maxLength": "com.ninastoessinger.word-o-mat.maxLength",
            "case": "com.ninastoessinger.word-o-mat.case",
            "limitToCharset": "com.ninastoessinger.word-o-mat.limitToCharset",
            "matchMode": "com.ninastoessinger.word-o-mat.matchMode",
            "matchPattern": "com.ninastoessinger.word-o-mat.matchPattern",
            "reqMarkColor": "com.ninastoessinger.word-o-mat.markColor",
            "source": "com.ninastoessinger.word-o-mat.source"  # <-- Added this line
        }
        for variableName, pref in prefsToLoad.items():
            setattr(self, variableName, getExtensionDefault(pref))
        try:
            self.limitToCharset = int(self.limitToCharset)
        except:
            self.limitToCharset = 1
        # parse mark color pref
        # print "***", self.reqMarkColor
        if self.reqMarkColor != "None":
            if type(self.reqMarkColor) is tuple:
                self.reqMarkColor = tuple(float(i) for i in self.reqMarkColor)
            else:
                self.reqMarkColor = "None"
        # print "loaded mark color pref: ", self.reqMarkColor

    def baseChangeCallback(self, sender):
        """If the selected base was changed, check if the color swatch needs to be shown/hidden."""
        colorSwatch = 1 if sender.get() == 3 else 0
        self.toggleColorSwatch(colorSwatch)

    def toggleColorSwatch(self, show=1):
        """Toggle display of the mark color swatch."""
        endY = -27 if show == 1 else -0
        self.g1.base.setPosSize((0, 61, endY, 20))
        '''
        self.g1.colorWell.show(show)
        '''

    def switchMatchModeCallback(self, sender):
        """Check if the UI needs toggling between text/grep mode input fields."""
        self.matchMode = "grep" if sender.get() == 1 else "text"
        self.toggleMatchModeFields()

    def toggleMatchModeFields(self):
        """Toggle between showing text or grep mode input fields."""
        t = self.matchMode == "text"
        g = not t
        self.g2.textMode.show(t)
        self.g2.grepMode.show(g)

    def loadREReference(self, sender):
        """Loads the RE syntax reference in a webbrowser."""
        url = "https://docs.python.org/3.6/library/re.html#regular-expression-syntax"
        webbrowser.open(url, new=2, autoraise=True)

    def readExtDefaultBoolean(self, string):
        """Read a Boolean saved as a string from the prefs."""
        return string == "True"

    def writeExtDefaultBoolean(self, var):
        """Write a Boolean to the prefs as a string."""
        if var:
            return "True"
        return "False"

    def loadDictionaries(self):
        """Load the available wordlists from the dictionaries folder structured by writing systems."""
        self.dictWords = {}
        self.allWords = []
        self.outputWords = []

        import os

        # Define the path to the dictionaries folder relative to this file
        dictFolder = os.path.join(os.path.dirname(__file__), "dictionaries")

        self.languagesByWS = {}  # Maps writing system -> list of language names
        self.writingSystems = []  # List of writing system names

        contentLimit = '*****'  # If a header exists, ignore lines before this delimiter

        if os.path.exists(dictFolder):
            # Loop over each subfolder (writing system)
            for writingSystem in os.listdir(dictFolder):
                wsPath = os.path.join(dictFolder, writingSystem)
                if os.path.isdir(wsPath):
                    # Initialize the language list for this writing system
                    self.languagesByWS[writingSystem] = []
                    for fileName in os.listdir(wsPath):
                        if fileName.lower().endswith(".txt"):
                            language = os.path.splitext(fileName)[0]
                            self.languagesByWS[writingSystem].append(language)

                            filePath = os.path.join(wsPath, fileName)
                            try:
                                with codecs.open(filePath, mode="r", encoding="utf-8") as fo:
                                    lines = fo.read().splitlines()
                            except Exception as e:
                                Message("Error", "Could not load dictionary file:\n%s" % filePath)
                                continue

                            try:
                                contentStart = lines.index(contentLimit) + 1
                                lines = lines[contentStart:]
                            except ValueError:
                                pass

                            # Store using a tuple key: (writingSystem, language)
                            self.dictWords[(writingSystem, language)] = lines
            self.writingSystems = sorted(list(self.languagesByWS.keys()))
        else:
            Message("Error", "Dictionaries folder not found at:\n%s" % dictFolder)

        # Optionally, load the user dictionary as before (if needed)
        try:
            with open('/usr/share/dict/words', 'r') as userFile:
                lines = userFile.read().splitlines()
            self.dictWords[("User", "user")] = lines
            if "User" in self.languagesByWS:
                self.languagesByWS["User"].append("user")
            else:
                self.languagesByWS["User"] = ["user"]
                self.writingSystems.append("User")
        except Exception as e:
            Message("Error", "Could not load user dictionary:\n%s" % str(e))

    def changeSourceCallback(self, sender):
        """On changing source/wordlist, check if a custom word list should be loaded."""
        customIndex = len(self.textfiles) + 2
        if sender.get() == customIndex:  # Custom word list
            try:
                # filePath = getFile(title="Load custom word list", messageText="Select a text file with words on separate lines", fileTypes=["txt"])[0] # open dialog from the vanilla version used in Glyphs 2 is not working in 10.15 (and above) any more. So if we drop Glyphs 2 support, this
                filePath = GetOpenFile(message="Load custom word list. Select a text file with words on separate lines", filetypes=["txt"])
            except TypeError:
                filePath = None
                self.customWords = []
                print("word-o-mat: Input of custom word list canceled, using default")
            if filePath is not None:
                fo = codecs.open(filePath, mode="r", encoding="utf-8")
                lines = fo.read()
                fo.close()
                # self.customWords = lines.splitlines()
                self.customWords = []
                for line in lines.splitlines():
                    w = line.strip()  # strip whitespace from beginning/end
                    self.customWords.append(w)

    def fontCharacters(self, font):
        """Check which Unicode characters are available in the font."""
        if not font:
            return []
        charset = []
        gnames = []
        for g in font.glyphs:
            if g.unicode is not None:
                try:
                    charset.append(g.charString())
                    gnames.append(g.name)
                except ValueError:
                    pass
        return charset, gnames

    # INPUT HANDLING
    def getInputString(self, field, stripColon):
        """Read an input string from a field, and convert it to a list of glyphnames."""
        inputString = field.get()
        pattern = re.compile(" *, *| +")
        if stripColon:
            i = inputString.find(":")
            if i != -1:
                inputString = inputString[i + 1:]
        result1 = pattern.split(inputString)

        result2 = []
        for c in result1:
            if len(c) > 1:  # glyph names
                if self.f is not None:
                    g = self.f.glyphs[c]
                    if g:
                        value = g.unicodeChar()
                        if value > 0:
                            result2.append(chr(value))
                        else:  # unicode not set
                            Message(title="word-o-mat", message="Glyph \"%s\" was found, but does not appear to have a Unicode value set. It can therefore not be processed, and will be skipped." % c)
                    else:
                        Message(title="word-o-mat", message="Conflict: Character \"%s\" was specified as required, but not found. It will be skipped." % c)
                else:
                    Message(title="word-o-mat", message="Sorry, matching by glyph name is only supported when a font is open. Character \"%s\" will be skipped." % c)
            else:  # character values
                result2.append(c)
        result = [s for s in result2 if s]
        return result

    def getIntegerValue(self, field):
        """Get an integer value (or if not set, the placeholder) from a field."""
        try:
            returnValue = int(field.get())
        except ValueError:
            returnValue = int(field.getPlaceholder())
            field.set(returnValue)
        return returnValue

    # INPUT CHECKING

    def checkReqVsFont(self, required, limitTo, fontChars, customCharset):
        """Check if a char is required from a font/selection/mark color that doesn't have it."""
        if not limitTo:
            return True
        else:
            if len(customCharset) > 0:
                useCharset = customCharset
                messageCharset = "selection of glyphs you would like me to use"
            else:
                useCharset = fontChars
                messageCharset = "font"
            for c in required:
                if c not in useCharset:
                    Message(title="word-o-mat", message="Conflict: Character \"%s\" was specified as required, but not found in the %s." % (c, messageCharset))
                    return False
            return True

    def checkReqVsLen(self, required, maxLength):
        """Check for conflicts between number of required characters and specified word length.
        Only implemented for text input for now.
        """
        if self.matchMode != "grep":
            if len(required) > maxLength:
                Message(title="word-o-mat", message="Conflict: Required characters exceed maximum word length. Please revise.")
                return False
        return True

    def checkReqVsCase(self, required, case):
        """Check that required letters do not contradict case selection.

        This seems to be a frequent source of user error.
        Only implemented for text mode (character list), not grep.
        """

        errNotLower = "word-o-mat: Conflict: You have specified all-lowercase words, but required uppercase characters. Please revise."
        errNotUpper = "word-o-mat: Conflict: You have specified words in ALL CAPS, but required lowercase characters. Please revise."

        if self.matchMode != "grep":
            # all lowercase words -- catch caps
            if case == 1:
                for c in required:
                    if not c.islower():
                        Message(errNotLower)
                        return False
                return True

            # all caps -- catch lowercase letters
            elif case == 3:
                for c in required:
                    if not c.isupper():
                        Message(errNotUpper)
                        return False
                return True
        return True

    def checkMinVsMax(self, minLength, maxLength):
        """Check user input for minimal/maximal word length and see if it makes sense."""
        if not minLength <= maxLength:
            Message(title="word-o-mat", message="Confusing input for minimal/maximal word length. Please fix.")
            return False
        return True

    def checkRE(self):
        """Check if the regular expression entered by the user compiles."""
        if self.matchMode == "grep":
            try:
                self.matchPatternRE = re.compile(self.matchPattern)
                return True
            except re.error:
                self.matchPatternRE = None
                Message(title="word-o-mat", message="Could not compile regular expression.")
                return False
        else:
            self.matchPatternRE = None
            return True

    def checkInput(self, limitTo, fontChars, customCharset, required, minLength, maxLength, case):
        """Run the user input through all the individual checking functions."""

        requirements = [
            (self.checkReqVsLen, [required, maxLength]),
            (self.checkReqVsFont, [required, limitTo, fontChars, customCharset]),
            (self.checkReqVsCase, [required, case]),
            (self.checkMinVsMax, [minLength, maxLength]),
            (self.checkRE, []),
        ]
        for reqFunc, args in requirements:
            if not reqFunc(*args):
                return False
        return True

    # OUTPUT SORTING

    def sortWordsByWidth(self, wordlist):
        """Sort output word list by width."""
        f = CurrentFont()
        wordWidths = []

        for word in wordlist:
            unitCount = 0
            for char in word:
                try:
                    glyphWidth = f[char].width
                except:
                    try:
                        gname = self.glyphNamesForValues[char]
                        glyphWidth = f[gname].width
                    except:
                        glyphWidth = 0
                unitCount += glyphWidth
            # add kerning
            for i in range(len(word) - 1):
                pair = list(word[i:i + 2])
                unitCount += int(self.findKerning(pair))
            wordWidths.append(unitCount)

        wordWidths_sorted, wordlist_sorted = zip(*sorted(zip(wordWidths, wordlist)))  # thanks, stackoverflow
        return wordlist_sorted

    def findKerning(self, chars):
        """Helper function to find kerning between two given glyphs.
        This assumes MetricsMachine style group names."""
        ''' # code for RF
        markers = ["@MMK_L_", "@MMK_R_"]
        keys = [c for c in chars]

        for i in range(2):
            allGroups = self.f.groups.findGlyph(chars[i])
            if len(allGroups) > 0:
                for g in allGroups:
                    if markers[i] in g:
                        keys[i] = g
                        continue

        key = (keys[0], keys[1])
        if key in self.f.kerning:
            return self.f.kerning[key]
        else:
            return 0
        '''
        # code for Glyphs
        glyph1 = self.f.glyphForCharacter_(ord(chars[0]))
        glyph2 = self.f.glyphForCharacter_(ord(chars[1]))
        # print("chars", chars, glyph1, glyph2)
        masterId = self.f.masters[0].id
        kerning = self.f.kerningForFontMasterID_firstGlyph_secondGlyph_direction_(masterId, glyph1, glyph2, 0)
        if kerning < 100000:
            return kerning
        return 0

    def makeWords(self, sender=None):
        """Parse user input, save new values to prefs, compile and display the resulting words.
        I think this function is too long and bloated, it should be taken apart. ########
        """
        global warned
        self.f = CurrentFont()

        if self.f is not None:
            self.fontChars, self.glyphNames = self.fontCharacters(self.f)
            self.glyphNamesForValues = {self.fontChars[i]: self.glyphNames[i] for i in range(len(self.fontChars))}
        else:
            self.fontChars = []
            self.glyphNames = []

        self.wordCount = self.getIntegerValue(self.g1.wordCount)
        self.minLength = self.getIntegerValue(self.g1.minLength)
        self.maxLength = self.getIntegerValue(self.g1.maxLength)
        self.case = self.g1.case.get()
        self.customCharset = []

        self.limitToCharset = self.g1.base.get()

        if self.limitToCharset == 2:  # use selection
            if len(self.f.selection) == 0:  # nothing selected
                Message(title="word-o-mat",
                        message="No glyphs were selected in the font window. Will use any characters available in the current font.")
                self.g1.base.set(1)  # use font chars
            else:
                try:
                    self.customCharset = []
                    for g in self.f.selection:
                        value = g.unicodeChar()
                        if value > 0:
                            self.customCharset.append(chr(value))
                except AttributeError:
                    pass

        elif self.limitToCharset == 3:  # use mark color
            self.customCharset = []
            if len(self.customCharset) == 0:
                Message(title="word-o-mat",
                        message="Found no glyphs that match the specified mark color. Will use any characters available in the current font.")
                self.g1.base.set(1)  # use font chars
                self.toggleColorSwatch(0)

            self.matchMode = "text" if self.g2.matchMode.get() == 0 else "grep"  # adjust match mode accordingly

        self.requiredLetters = self.getInputString(self.g2.textMode.mustLettersBox, False)
        self.requiredGroups[0] = self.getInputString(self.g2.textMode.group1box, True)
        self.requiredGroups[1] = self.getInputString(self.g2.textMode.group2box, True)
        self.requiredGroups[2] = self.getInputString(self.g2.textMode.group3box, True)
        self.matchPattern = self.g2.grepMode.grepBox.get()

        self.banRepetitions = self.g3.checkbox0.get()
        self.outputWords = []  # initialize/empty

        # ---- NEW DICTIONARY SELECTION USING TWO DROP-DOWN MENUS ----
        selectedWS = self.g1.writingSystem.getItem()
        selectedLanguage = self.g1.language.getItem()
        if (selectedWS, selectedLanguage) in self.dictWords:
            self.allWords = self.dictWords[(selectedWS, selectedLanguage)]
        else:
            Message(title="Error", message="Selected dictionary not found.")
            return

        # store new values as defaults
        markColorPref = self.reqMarkColor if self.reqMarkColor is not None else "None"

        extDefaults = {
            "wordCount": self.wordCount,
            "minLength": self.minLength,
            "maxLength": self.maxLength,
            "case": self.case,
            "limitToCharset": self.limitToCharset,
            "source": "",  # Not used anymore, but kept for backwards compatibility if needed
            "matchMode": self.matchMode,
            "matchPattern": self.matchPattern,  # non compiled string
            "markColor": markColorPref,
        }
        for key, value in extDefaults.items():
            setExtensionDefault("com.ninastoessinger.word-o-mat." + key, value)

        # go make words
        if self.checkInput(self.limitToCharset, self.fontChars, self.customCharset, self.requiredLetters,
                           self.minLength, self.maxLength, self.case):

            checker = wordcheck.wordChecker(self.limitToCharset, self.fontChars, self.customCharset,
                                            self.requiredLetters, self.requiredGroups, self.matchPatternRE,
                                            self.banRepetitions, self.minLength, self.maxLength,
                                            matchMode=self.matchMode)

            for i in self.allWords:
                if len(self.outputWords) >= self.wordCount:
                    break
                else:
                    w = choice(self.allWords)
                    if self.case == 1:
                        w = w.lower()
                    elif self.case == 2:
                        try:
                            ijs = ["ij", "IJ", "Ij"]
                            # Note: Adjust this section if needed based on the language selected.
                            if w[:2] in ijs:
                                w = "IJ" + w[2:]
                            else:
                                w = w.title()
                        except IndexError:
                            w = w.title()
                    elif self.case == 3:
                        if u"ß" in w:
                            w = w.replace(u"ß", "ss")
                        w = w.upper()
                    elif self.case == 4:
                        w = ransom(w)

                    if checker.checkWord(w, self.outputWords):
                        self.outputWords.append(w)

            # output
            if len(self.outputWords) < 1:
                Message(title="word-o-mat", message="no matching words found <sad trombone>")
            else:
                joinString = " "
                if self.g3.listOutput.get():
                    joinString = "\\n"
                    self.outputWords = self.sortWordsByWidth(self.outputWords)
                outputString = joinString.join(self.outputWords)
                try:
                    sp = OpenSpaceCenter(CurrentFont())
                    sp.setRaw(outputString)
                except:
                    if not warned:
                        Message(title="word-o-mat",
                                message="No open fonts found; words will be displayed in the Output Window.")
                    warned = True
                    print("word-o-mat:", outputString)
        else:
            print("word-o-mat: Aborted because of errors")

    def fontClosed(self, info):
        """Check if there are any fonts left open, otherwise disable relevant UI controls."""
        if len(AllFonts()) <= 1:
            self.g1.base.set(0)  # use any characters
            self.g1.base.enable(False)

    def windowClose(self, sender):
        """Remove observers when the extension window is closed."""
        removeObserver(self, "fontDidOpen")
        removeObserver(self, "fontWillClose")


def ransom(s):
    """Randomly convert the case in the string s so that
    it looks like a ransom note.
    """

    def flip(c):
        if random.random() < 0.5:
            return c.lower()
        else:
            return c.upper()
    return "".join(flip(c) for c in s)
