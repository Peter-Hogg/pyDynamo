from collections import deque

from model import *

# SWC file -> Tree
def importFromSWC(path):
    childMap, metadata, comments = {}, {}, []

    swcLines = [line.rstrip('\n') for line in open(path)]
    for line in swcLines:
        # Process metdata values into map:
        metaKey, metaValue = _parseMeta(line)
        if metaKey is not None:
            metadata[metaKey] = metaValue

        # Collect comments, just in case it's useful for later:
        if line[0] == '#':
            comments.append(line)
            continue

        # And otherwise, build the tree:
        # n,type,x,y,z,radius,parent
        parts = line.split(' ')
        if len(parts) != 7:
            print ("Unsupported SWC file format. All node lines must be n,type,x,y,z,radius,parent")
            return None
        nodeID, nodeType, x, y, z, radius, parent = tuple(parts)
        x, y, z = float(x), float(y), float(z) # TODO: Scale?
        if parent not in childMap:
            childMap[parent] = []
        childMap[parent].append((nodeID, (x, y, z))) # TODO: Use nodeType / radius later

    return _convertChildMapToTree(childMap)

# Given mapping of parent -> list of (child ID, child XYZ), convert this to a tree model
def _convertChildMapToTree(childMap):
    if '-1' not in childMap or len(childMap['-1']) != 1:
        print ("Can't parse SWC file: Has more than one Soma (parent -1)")
        return None
    somaID, somaLocation = childMap['-1'][0]

    tree = Tree()
    tree.rootPoint = Point(somaID, somaLocation)

    # Keep track of where branches have come off that still need processing
    toProcess = deque()
    toProcess.append(somaID)

    branchCounter = 0
    while len(toProcess) > 0:
        nextParentID = toProcess.popleft()
        nLeft = sum([len(childMap[k]) for k in childMap])
        print ("%d remain, Processing %s " % (nLeft, nextParentID))
        if nextParentID not in childMap or len(childMap[nextParentID]) == 0:
            continue
        parentPoint = tree.getPointByID(nextParentID)
        assert parentPoint is not None

        # Start this branch, but remember parent if it has more coming off...
        branchPointID, branchPointLocation = childMap[nextParentID][0]
        childMap[nextParentID].pop(0)
        if len(childMap[nextParentID]) > 0:
            toProcess.append(nextParentID)

        newBranch = Branch('%04x' % branchCounter)
        newBranch.setParentPoint(parentPoint)
        branchCounter += 1

        while True:
            # Walk along the branch, adding points as we go
            newBranch.addPoint(Point(branchPointID, branchPointLocation))
            oldBranchPointID = branchPointID
            if branchPointID not in childMap or len(childMap[branchPointID]) == 0:
                break
            # Remember any intermediate points that have more children coming off them
            branchPointID, branchPointLocation = childMap[oldBranchPointID][0]
            childMap[oldBranchPointID].pop(0)
            if len(childMap[oldBranchPointID]) > 0:
                toProcess.append(oldBranchPointID)
        tree.addBranch(newBranch)
    # Done!
    return tree


# Parse initial lines, like #SR_ratio = 0.333333
def _parseMeta(line):
    if line[0] != '#' or '=' not in line:
        return None, None
    at = line.find('=')
    return line[1:at].strip(), line[at+1:].strip()