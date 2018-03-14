import numpy as np

from .addedSubtractedTransitioned import addedSubtractedTransitioned
from .TDBL import TDBL

from model import FiloType

# Set these to tree / branch indexes to print TDBL information for that specific target.
DEBUG_TREE = -1
DEBUG_BRANCH = -1

def motility(trees,
    excludeAxon=True,
    excludeBasal=True,
    includeAS=False,
    terminalDist=10,
    filoDist=10
):
    print ("\n\nCalculating motility...")
    filoTypes, added, subtracted, _, masterChangedOut, _ = \
        addedSubtractedTransitioned(trees, excludeAxon, excludeBasal, terminalDist, filoDist)

    # All outputs will be [# trees][# branches]
    nTrees = len(trees)
    nBranches = len(trees[-1].branches)
    resultShape = (nTrees, nBranches)
    filoLengths = np.full(resultShape, np.nan)

    allTDBL = np.zeros(nTrees)

    for treeIdx, tree in enumerate(trees):
        allTDBL[treeIdx] = TDBL(tree, excludeAxon, excludeBasal, includeFilo=True, filoDist=filoDist)
        for branch in tree.rootPoint.children:
            _calcFiloLengths(filoLengths, treeIdx, branch, excludeAxon, excludeBasal, filoDist)

    lengthAdded = filoLengths[1:, :]
    lengthSubtracted = filoLengths[:-1, :]

    rawMotility = lengthAdded - lengthSubtracted
    rawMotility[masterChangedOut] = np.nan

    # including motility dtreeIdx, ue to additions/subtractions
    if includeAS:
        rawMotility[added] = lengthAdded[added]
        rawMotility[subtracted] = -lengthSubtracted[subtracted]

    filoLengthWithNan = np.array(filoLengths[:rawMotility.shape[0], :])
    filoLengthWithNan[np.isnan(rawMotility)] = np.nan

    nFilo = np.sum((filoTypes > FiloType.ABSENT) & (filoTypes < FiloType.BRANCH_ONLY), axis=1)

    # Normalize by pre stats, not post:
    allTDBL, nFilo = allTDBL[:-1], nFilo[:-1]

    motilities = {
        'raw': rawMotility,
        'rawTDBL': np.nansum(rawMotility, axis=1) / allTDBL,
        'rawFilo': np.nansum(rawMotility, axis=1) / np.nansum(filoLengthWithNan, axis=1),
        'rawNFilo': np.nansum(rawMotility, axis=1) / nFilo
    }
    return motilities, filoLengths


def _calcFiloLengths(filoLengths, treeIdx, branch, excludeAxon, excludeBasal, filoDist):
    branchIdx = branch.indexInParent()
    # if ~np.isnan(filoLengths[branchIdx]):
        # print ("SKIPPING")
        # return filoLengths[branchIdx] # Already calculated, so no need to do it again.

    pointsWithRoot = [branch.parentPoint] + branch.points

    # 1) If the branch has not been created yet, or is empty, abort
    if len(pointsWithRoot) < 2:
        if treeIdx == DEBUG_TREE and branchIdx == DEBUG_BRANCH:
            print ("Branch %d is empty, zero dist" % (branchIdx + 1))
        filoLengths[treeIdx][branchIdx] = 0
        return 0
    # 2) If the branch contains an 'axon' label, abort
    if excludeAxon and _lastPointWithLabel(pointsWithRoot, 'axon') >= 0:
        if treeIdx == DEBUG_TREE and branchIdx == DEBUG_BRANCH:
            print ("Branch %d is axon, nan dist" % (branchIdx + 1))
        filoLengths[treeIdx][branchIdx] = np.nan
        return np.nan
    # 3) If the branch is a basal dendrite, abort
    if excludeBasal and _lastPointWithLabel(pointsWithRoot, 'basal') >= 0:
        if treeIdx == DEBUG_TREE and branchIdx == DEBUG_BRANCH:
            print ("Branch %d is basal, nan dist" % (branchIdx + 1))
        filoLengths[treeIdx][branchIdx] = np.nan
        return np.nan
    # 4) If we're a filo, set and stop:
    isFilo, branchLength = branch.isFilo(filoDist)
    if isFilo:
        if treeIdx == DEBUG_TREE and branchIdx == DEBUG_BRANCH:
            print ("Branch %d is filo, dist %f" % (branchIdx + 1, branchLength))
            print ([p.location for p in ([branch.parentPoint] + branch.points)])
        filoLengths[treeIdx][branchIdx] = branchLength
        return

    # 5) Recurse to fill filolengths cache for all child branches:
    totalLength, totalLengthToLastBranch = branch.worldLengths()
    for point in branch.points:
        for childBranch in point.children:
            _calcFiloLengths(filoLengths, treeIdx, childBranch, excludeAxon, excludeBasal, filoDist)

    # 6) Add the final filo for this branch if it's short enough.
    lengthPastLastBranch, filoLength = filoDist + 1, 0
    if totalLengthToLastBranch > 0:
        lengthPastLastBranch = totalLength - totalLengthToLastBranch
    if lengthPastLastBranch < filoDist:
        filoLength = lengthPastLastBranch
    if treeIdx == DEBUG_TREE and branchIdx == DEBUG_BRANCH:
        print ("Branch %d recursed, has dist %f" % (branchIdx + 1, filoDist))
    filoLengths[treeIdx][branchIdx] = filoLength
    # return filoLength

# Return the index of the last point whose label contains given text, or -1 if not found.
# TODO - move somewhere common.
def _lastPointWithLabel(points, label):
    lastPointIdx = -1
    for i, point in enumerate(points):
        if point.annotation.find(label) != -1:
            lastPointIdx = i
    return lastPointIdx