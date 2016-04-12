"""
    ===================================================
    parseSpec.py - Structured English to LTL Translator
    ===================================================

    Module that parses a set of structured English sentences into the
    corresponding LTL subformulas using a context-free grammar
"""

import re
import os
import copy

import logging

try:
    from nltk.grammar import FeatureGrammar
    from nltk.sem import interpret_sents
except ImportError as e:
    logging.error("Either you do not have NLTK installed " +
                  "or you are using an old version of NLTK. " +
                  "Install NLTK 3 to use the updated API.")
    raise e


def writeSpec(text, sensorList, regionList, robotPropList):
    ''' This function creates the Spec dictionary that contains the parsed LTL
        subformulas. It takes the text that contains the structured English,
        the list of sensor propositions, the list containing
        the region names and the list of robot propositions (other than regions).
    '''

    #Begin optimistically
    failed = False

    #Initialize the dictionary
    spec = {}
    spec['EnvInit']= ''
    spec['EnvTrans']= ''
    spec['EnvGoals']= ''
    spec['SysInit']= ''
    spec['SysTrans']= ''
    spec['SysGoals']= ''

    linemap = {}
    linemap['EnvInit']= []
    linemap['EnvTrans']= []
    linemap['EnvGoals']= []
    linemap['SysInit']= []
    linemap['SysTrans']= []
    linemap['SysGoals']= []

    LTL2LineNo = {}

    internal_props = []

    sensorList = [sensor.lower() for sensor in sensorList]
    regionList = [region.lower() for region in regionList]
    robotPropList = [robotProp.lower() for robotProp in robotPropList]

    allProps = sensorList + regionList + robotPropList

    #Initialize dictionaries mapping group names to lists of groups
    regionGroups = {}
    sensorGroups = {}
    actionGroups = {}
    allGroups = {}

    #Initialize dictionary mapping propositions to sets of 'corresponding' propositions
    correlations = {}

    #Open CFG file
    #TODO: Make path independent
    grammarFile = open('lib/structuredEnglish.fcfg','rb')
    grammarText = grammarFile.read()

    #Generate regular expression to match sentences defining groups
    groupDefPattern = r'\s*group (?P<name>\w+) is (?P<items>(?:\w+)(?:,[ \w]+)*)'
    r_groupDef = re.compile(groupDefPattern, re.I)

    #Generate regular expression to match sentences defining correlations
    #TODO: Replace "correlations" woth "group/proposition correspondence" here and elsewhere.
    correlationDefPattern = r'((?:\w+,? )+)correspond(?:s)? to((?:,? \w+)+)'
    r_correlationDef = re.compile(correlationDefPattern, re.I)

    #Generate regular expression to match group operation sentences
    #TODO: Remove the word "group" after add to. What else would we be adding a proposition to?
    groupOpPattern = r'(?P<operation>add to|remove from)\s+group\s+(?P<groupName>\w+)'
    r_groupOp = re.compile(groupOpPattern, re.I)

    #Begin parsing input text
    textLines = text.split('\n')
    linesToParse = []
    allLines = range(len(textLines))

    #Scan lines for definitions and update grammar
    for lineInd in allLines:
        #If it is an empty line, ignore it
        if re.search(r'^(\s*)$',textLines[lineInd]):
            continue

        #If the sentence is a comment, ignore it
        if re.search(r'^\s*#',textLines[lineInd]):
            continue

        #Make line lowercase
        line = textLines[lineInd].lower()

        #Put exactly one space before and after parentheses
        line = re.sub(r'\s*?(\(|\))\s*?',r' \1 ',line)

        #If there is a newline at the end, remove it
        if re.search('\n$',line):
            line = re.sub('\n$',' ',line)

        #print line

        #Find any group definitons
        m_groupDef = r_groupDef.match(line)
        if m_groupDef:
            #Add an entry to the grammar for the group defined in this line

            groupName = m_groupDef.group('name')
            groupItems = filter(lambda x: x != None and x!='empty', m_groupDef.group('items').replace(' or ',' | ').split(', '))
            groupItems = [item.strip() for item in groupItems]

            #Determine which kind of group this could be defining
            regionGroup = True
            sensorGroup = True
            actionGroup = True
            for item in groupItems:
                if item not in regionList and item != 'empty' and not all(x in regionList for x in item.split(' | ')):
                    regionGroup = False
                if item not in sensorList and item != 'empty'and not all(x in sensorList for x in item.split(' | ')):
                    sensorGroup = False
                if item not in robotPropList and item != 'empty'and not all(x in robotPropList for x in item.split(' | ')):
                    actionGroup = False

            #Extend grammar for all possible group types
            if regionGroup:
                grammarText += '\nGROUP[SEM=<' + groupName + '>] -> \'' + groupName + '\' | \''+groupName+'s\' | \''+re.sub(r'(\w+)s',r'\1',groupName)+'\''
                regionGroups[groupName] = groupItems
                #print '\tRegion groups updated: ' + str(regionGroups)
            if sensorGroup:
                grammarText += '\nSENSORGROUP[SEM=<' + groupName + '>] -> \'' + groupName + '\' | \''+groupName+'s\' | \''+re.sub(r'(\w+)s',r'\1',groupName)+'\''
                sensorGroups[groupName] = groupItems
                #print '\tSensor groups updated: ' + str(sensorGroups)
            if actionGroup:
                grammarText += '\nACTIONGROUP[SEM=<' + groupName + '>] -> \'' + groupName + '\' | \''+groupName+'s\' | \''+re.sub(r'(\w+)s',r'\1',groupName)+'\''
                actionGroups[groupName] = groupItems
                #print '\tAction groups updated: ' + str(actionGroups)

            if regionGroup or sensorGroup or actionGroup:
                allGroups[groupName] = groupItems
            else:
                logging.error('Could not create group out of items: ' + ' '.join(groupItems))
                print('ERROR: Could not create group out of items: ' + ' '.join(groupItems))

        if m_groupDef: continue

        #Find any correlation definitions
        #TODO: Remove the need to explicitly define correspondence. Let it be optional. If missing, infer from use of corresponding operator.
        m_correlationDef = r_correlationDef.match(line)
        if m_correlationDef:
            keyItems = filter(lambda x: x != '', re.split(' |, |,', m_correlationDef.group(1)))
            valueItems = filter(lambda x: x != '', re.split(' |, |,', m_correlationDef.group(2)))
            if len(keyItems) != len(valueItems):
                print('Error: Correlations must be made in pairs!')
                failed = True
                continue
            if len(keyItems) == 1 and keyItems[0] in allGroups and valueItems[0] in allGroups:
                #We're defining a group-to-group correspondence now
                keyItems = allGroups[keyItems[0]]
                valueItems = allGroups[valueItems[0]]
            for prop in keyItems + valueItems:
                if prop not in allProps:
                    print('Error: Could not resolve proposition \'' + prop + '\'')
                    failed = True
                    continue
            #Add specified correlation(s) to dictionary of correlations
            nPairs = len(keyItems)
            for ind in range(0,nPairs):
                if keyItems[ind] in correlations:
                    correlations[keyItems[ind]].append(valueItems[ind])
                else:
                    correlations[keyItems[ind]] = [valueItems[ind]]
                #print '\tCorrelations updated: ' + keyItems[ind] + ' corresponds to ' + valueItems[ind]
            continue

        #Find any group operations but still add line for parsing
        m_groupOp = r_groupOp.search(line)
        while m_groupOp:
            propName = "_"+m_groupOp.group('operation').replace(' ','_')+'_'+m_groupOp.group('groupName')
            if propName not in robotPropList:
                robotPropList.append(propName.lower())
                internal_props.append(propName.lower())
            line = re.sub(m_groupOp.group(0),'do '+propName, line)
            textLines[lineInd] = line
            m_groupOp = r_groupOp.search(line)

        #If sentence doesn't match any of these, we can parse it with the grammar
        linesToParse.append(lineInd)

    #For generating our terminals from propositions, we add an extra '$' that will be stripped
    # after parsing because the NLTK semantics module will consider terms like 'r1' and 'r3' to
    # be alpha-equivalent and perform undesired alpha-substitution ('$r1' and '$r3' are left alone)

    #Add production rules for region names to our grammar string
    for region in regionList:
        grammarText += '\nREGION[SEM=<$'+region+'>] -> \''+region+'\''

    #Add production rules for action names to our grammar string
    for action in robotPropList:
        grammarText += '\nACTION[SEM=<$'+action+'>] -> \''+action+'\''

    #Add production rules for sensor names to our grammar string
    for sensor in sensorList:
        grammarText += '\nSENSOR[SEM=<$'+sensor+'>] -> \''+sensor+'\''

    #Generate NLTK feature grammar object from grammar string (NLTK 3 API)
    grammar = FeatureGrammar.fromstring(grammarText)

    #Iterate over the lines in the file
    for lineNo in linesToParse:

        line = textLines[lineNo].lower()
        #Put exactly one space before and after parentheses
        line = re.sub(r'\s*?(\(|\))\s*?',r' \1 ',line)
        #print line

        # Parse input line using grammar; the result here is a collection
        # of pairs of syntax trees and semantic representations in a
        # prefix first-order-logic syntax (using NLTK 3 API)
        parses = interpret_sents([line], grammar, 'SEM')[0]

        if len(parses) == 0:
            print('Error: No valid parse found for: ' + line)
            failed = True

        uniqueParses = []

        #Iterate over all parse trees found
        for (syntree, semrep) in parses:

            semstring = str(semrep)

            #We are not interested multiple parse trees that
            # produce the same LTL formula, so skip them
            if semstring in uniqueParses: continue

            uniqueParses.append((syntree, semstring))

        #if len(uniqueParses) > 1:
        #    showParseDiffs(uniqueParses)

        semstring = uniqueParses[0][1]

        #Expand initial conditions
        semstring = parseInit(semstring, sensorList, robotPropList)

        #Expand 'corresponding' phrases
        semstring = parseCorresponding(semstring, correlations, allGroups)

        #Expand 'stay' phrases
        semstring = parseStay(semstring, regionList)

        #Expand groups, 'each', 'any', and 'all'
        semstring = parseGroupEach(semstring, allGroups)
        semstring = parseGroupAny(semstring, allGroups)
        semstring = parseGroupAll(semstring, allGroups)

        #Trim any extra $'s attached to proposition names
        semstring = semstring.replace('$','')

        syntree_node_spec = syntree.label()['SPEC']


        #Liveness sentences should not contain 'next'
        if syntree_node_spec == 'SysGoals' or syntree_node_spec == 'EnvGoals':
            semstring = semstring.replace('Next','')

        if 'NextMem' in semstring:
                semstring = handleMemorySensors( semstring, sensorList )

        semstring = cleanNestedNext( semstring )

        #TODO: In environment safeties, all robot props must be PAST TENSE

        #Convert formula from prefix FOL to infix LTL and add it to
        # the appropriate section of the specification
        stringLTL = prefix2infix(semstring)

        if stringLTL != '':
            spec[syntree_node_spec] += stringLTL + ' & \n'
        linemap[syntree_node_spec].append(lineNo)
        LTL2LineNo[stringLTL] = lineNo

    # Set all empty subformulas to TRUE,
    # and remove last & in 'EnvGoals' and 'SysGoals'
    if spec['EnvInit'] == '':
        spec['EnvInit'] = 'TRUE & \n'
    if spec['EnvTrans'] == '':
        spec['EnvTrans'] = '[](TRUE) & \n'
    if spec['EnvGoals'] == '':
        spec['EnvGoals'] = '[]<>(TRUE) \n'
    else:
        # remove last &
        spec['EnvGoals'] = re.sub('& \n$','\n',spec['EnvGoals'])

    # No need to change anything in SysTrans,
    # since the transition relation is encoded anyway
    if spec['SysGoals'] == '':
        spec['SysGoals'] = '[]<>(TRUE)'
    else:
        # remove last &
        spec['SysGoals'] = re.sub('& \n$','\n',spec['SysGoals'])

    return spec,linemap,failed,LTL2LineNo,internal_props

def cleanNestedNext( semstring ):
    """
    >>> teststring = "Next abcdf abcfd Next"
    >>> cleanNestedNext( teststring )
    'Next abcdf abcfd Next'

    >>> teststring = "Next(Next(Next(x)))"
    >>> cleanNestedNext( teststring )
    '((Next(x)))'

    >>> teststring = "blablabla Next(bla) Next(Next(Next(x)))"
    >>> cleanNestedNext( teststring )
    'blablabla Next(bla) ((Next(x)))'
    """
    result = copy.copy(semstring)
    position = result.find('Next')
    while position >= 0:
        opened = 0
        closed = 0
        endposition = -1
        for i in range( len( result[position:] ) ):
            if result[position+i]  == '(':
                opened += 1
            elif result[position+i]  == ')':
                closed += 1
            if opened > 0 and opened ==  closed:
                endposition = position+i+1
		assert endposition > 0,result 
                break

        if endposition < 0:
            position = result.find('Next',position+1)
        # what the Next is applied to
        substring = result[ position+4 : endposition ]
        if 'Next' in substring:
            new_substring = substring
            result2 = result[:position] + new_substring + result[endposition:]
            result = result2
        position = result.find('Next',position+1)
    return result

def handleMemorySensors( semstring, sensorList ):
    result = copy.copy(semstring)
    position = result.find('NextMem')
    while position >= 0:
        opened = 0
        closed = 0
        endposition = -1
        for i in range( len( result[position:] ) ):
            if result[position+i]  == '(':
                opened += 1
            elif result[position+i]  == ')':
                closed += 1
            if opened > 0 and opened ==  closed:
                endposition = position+i+1
		assert endposition > 0,result 
                break

        memsubstring = result[ position : endposition ]

        new_memsubstring = memsubstring
        for sensor_prop in sensorList:
            if sensor_prop in memsubstring:
                new_memsubstring = new_memsubstring.replace( sensor_prop, 
                        'Next('+sensor_prop+')' )

        new_memsubstring = new_memsubstring.replace('NextMem', '')[1:-1] # remove extra parentheses too
        result2 = result[:position] + new_memsubstring + result[endposition:]
        result = result2
        
        position = result.find('NextMem')

    #sanity check for number of parentheses
    opened = 0
    closed = 0
    endposition = -1
    for i in range( len( result ) ):
        if result[i]  == '(':
            opened += 1
        elif result[i]  == ')':
            closed += 1
    assert opened==closed,result

    return result 

def parseInit(semstring, sensorList, robotPropList):
    if semstring.find('$EnvStart') != -1:
        prefix = '!' if semstring.find('$EnvStart(FALSE)') != -1 else ''
        semstring = 'And(' + prefix + (',And(' + prefix).join(sensorList[0:-1]) + ',' + prefix + sensorList[-1] + ')'*(len(sensorList) - 1)
    elif semstring.find('$RobStart') != -1:
        prefix = '!' if semstring.find('$RobStart(FALSE)') != -1 else ''
        propsToInit = [val for val in robotPropList if not re.search(val,semstring, re.I)]
        initString = 'And(' + prefix + (',And(' + prefix).join(propsToInit[0:-1]) + ',' + prefix + propsToInit[-1] + ')'*(len(propsToInit) - 1)
        semstring = re.sub(r'\$RobStart\(\w+\)',initString,semstring)
    return semstring

def parseStay(semstring, regions):
    def appendStayClause(ind):
        if ind == len(regions) - 1:
            return 'Iff(Next('+regions[ind]+'),'+regions[ind]+')'
        else:
            return 'And(Iff(Next('+regions[ind]+'),'+regions[ind]+'),'+appendStayClause(ind+1)+')'
    if semstring.find('$Stay') != -1:
        stay = appendStayClause(0)
        #return semstring.replace('$Stay',stay)
        # Just insert the "STAY_THERE" macro to be dealt with by specCompiler
        return semstring.replace('Next($Stay)','STAY_THERE').replace('$Stay','STAY_THERE')
    else:
        return semstring

def parseGroupAll(semstring, allGroups):
    while semstring.find('$All') != -1:
        groupName = re.search(r'\$All\((\w+)\)',semstring).groups()[0]
        if groupName in allGroups:
            group = allGroups[groupName]
            if len(group) == 0: return re.sub(r'\$All\('+groupName+'\)', 'TRUE', semstring)
            if len(group) == 1: return re.sub(r'\$All\('+groupName+'\)', group[0], semstring)
            allClause = 'And(' + ',And('.join(group[0:-1]) + ',' + group[-1] + ')'*(len(group)-1)
            semstring = re.sub(r'\$All\(' + groupName + '\)', allClause, semstring)
            #print('Group '+groupName+': '+str(group))
            #print('Expanded into: '+allClause)
        else:
            print('Error: Could not resolve group '+groupName)
    return semstring

def parseGroupAny(semstring, allGroups):
    while semstring.find('$Any') != -1:
        groupName = re.search(r'\$Any\((\w+)\)',semstring).groups()[0]
        if groupName in allGroups:
            group = allGroups[groupName]
            if len(group) == 0: return re.sub(r'\$Any\('+groupName+'\)', 'FALSE', semstring)
            if len(group) == 1: return re.sub(r'\$Any\('+groupName+'\)', group[0], semstring)
            anyClause = 'Or(' + ',Or('.join(group[0:-1]) + ',' + group[-1] + ')'*(len(group)-1)
            semstring = re.sub(r'\$Any\('+groupName+'\)', anyClause, semstring)
        else:
            print('Error: Could not resolve group '+groupName)
    return semstring

def parseGroupEach(semstring, allGroups):
    while semstring.find('$Each') != -1:
        groupName = re.search(r'\$Each\((\w+)\)',semstring).group(1)
        if groupName in allGroups:
            if len(allGroups[groupName]) == 0: return ''
            if len(allGroups[groupName]) == 1: return re.sub(r'\$Each\('+groupName+'\)', allGroups[groupName][0], semstring)
            newSentences = []
            for groupItem in allGroups[groupName]:
                newSentences.append(re.sub(r'\$Each\('+groupName+'\)',groupItem,semstring))
            semstring = 'And('+',And('.join(newSentences[0:-1])+','+newSentences[-1]+')'*(len(newSentences)-1)
        else:
            print('Error: Could not resolve group '+groupName)
    return semstring

def parseCorresponding(semstring, correlations, allGroups):
    if semstring.find('$Corr') != -1:
        m_Any = re.search(r'\$Any\((\w+)\)',semstring)
        m_Each = re.search(r'\$Each\((\w+)\)',semstring)
        corrGroups = re.findall(r'\$Corr\((\w+)\)',semstring)
        indexGroupName = ''
        indexGroup = []
        indexPhrase = ''
        if m_Any:
            indexGroupName = m_Any.groups()[0]
            indexPhrase = m_Any.group(0)
        elif m_Each:
            indexGroupName = m_Each.groups()[0]
            indexPhrase = m_Each.group(0)
        else:
            print('Error: \'corresponding\' must be be preceded by an \'any\' or \'each\' quantifier')
            failed = True
            return ''
        indexGroup = allGroups[indexGroupName]
        #Iterate over items in indexGroup, replacing each 'corresponding' with the
        # intersection of items correlated with indexItem and items in the relevant group
        newSentences = []
        for indexItem in indexGroup:
            if indexItem not in correlations:
                print('Error: no correlation found for item \'' + indexItem + '\' in group \'' + indexGroupName + '\'')
                return ''
            sent = semstring.replace(indexPhrase,indexItem)
            for valueGroupName in corrGroups:
                valueGroup = allGroups[valueGroupName]
                isect = [val for val in correlations[indexItem] if val in valueGroup]
                if len(isect) != 1:
                    print('Error: Items being quantified must correspond to exactly one item from \'corresponding\' groups')
                else:
                    sent = sent.replace('$Corr('+valueGroupName+')',isect[0])
            newSentences.append(sent)
        if len(newSentences) != len(indexGroup):
            print 'Error: cannot resolve correlations in \'' + semstring + '\''
            return ''
        #Build conjunction out of all generated sentences
        #TODO: Conjunction for "each" quantifier, disjunction for "any" quantifier. The scope should be as definined in the ICRA 2014 paper.
        if len(newSentences) == 0:
            semstring = ''
        elif len(newSentences) == 1:
            semstring = newSentences[0]
        else:
            semstring = 'And(' + ',And('.join(newSentences[0:-1]) + ',' + newSentences[-1] + ')'*(len(newSentences)-1)

    return semstring

def prefix2infix(prefixString):
    inList = re.split('[(),]+',prefixString)
    def opReduce(inList, index):
        if inList[index] == 'And':
            arg1, lastIndex1 = opReduce(inList, index + 1)
            arg2, lastIndex2 = opReduce(inList, lastIndex1 + 1)
            return '(' + arg1 + ' & ' + arg2 + ')', lastIndex2
        elif inList[index] == 'Or':
            arg1, lastIndex1 = opReduce(inList, index + 1)
            arg2, lastIndex2 = opReduce(inList, lastIndex1 + 1)
            return '(' + arg1 + ' | ' + arg2 + ')', lastIndex2
        elif inList[index] == 'Imp':
            arg1, lastIndex1 = opReduce(inList, index + 1)
            arg2, lastIndex2 = opReduce(inList, lastIndex1 + 1)
            return '(' + arg1 + ' -> ' + arg2 + ')', lastIndex2
        elif inList[index] == 'Iff':
            arg1, lastIndex1 = opReduce(inList, index + 1)
            arg2, lastIndex2 = opReduce(inList, lastIndex1 + 1)
            return '(' + arg1 + ' <-> ' + arg2 + ')', lastIndex2
        elif inList[index] == 'Not':
            arg, lastIndex = opReduce(inList, index + 1)
            return '!(' + arg + ')', lastIndex
        elif inList[index] == 'Next':
            arg, lastIndex = opReduce(inList, index + 1)
            return 'next(' + arg + ')', lastIndex
        elif inList[index] == 'Glob':
            arg, lastIndex = opReduce(inList, index + 1)
            return '[](' + arg + ')', lastIndex
        elif inList[index] == 'GlobFin':
            arg, lastIndex = opReduce(inList, index + 1)
            return '[]<>(' + arg + ')', lastIndex
        else:
            return inList[index], index

    return opReduce(inList, 0)[0]

def _findGroupsInCorrespondenceWithGroup(proj, group_name):
    """ Return a list of group names to which the group named `group_name` has a correspondence relation. """

    # TODO: Move this to parser?
    CorrespondenceDefinitionRE = re.compile(r"^\s*" + group_name + r"\s+corresponds?\s+to\s+(?P<groupB>\w+)", \
                                                re.MULTILINE | re.IGNORECASE)

    corresponding_groups = [m.group("groupB") for m in CorrespondenceDefinitionRE.finditer(proj.specText)]

    return corresponding_groups

if __name__=="__main__":
    import doctest
    doctest.testmod( )
