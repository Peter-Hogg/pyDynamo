import numpy as np

from typing import Any, List, Tuple

import pydynamo_brain.util as util
from pydynamo_brain.model import Tree, FiloType

def addedSubtractedTransitioned(
    trees: List[Tree],
    excludeAxon: bool=True,
    excludeBasal: bool=True,
    terminalDist: float=10.0,
    filoDist: float=10.0,
    **kwargs: Any
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Calculate added/subtracted/transitioned status of all branches across time.

    Args:
        trees (list): The structure of the tree across time.
        excludeAxon (bool): Flag indicating whether the motility of the axon should be skipped.
        excludeBasal (bool): Flag indicating whether the motility of basal dendrites should be skipped.
        terminalDist (float): Maximum distance between last branch and end of dendrite for that to be considered a filo.
        filoDist (float): Maximum distance a branch can be for it to be considered a filo.

    Returns:
        TODO
    """

    nTrees = len(trees)
    branchIDList = util.sortedBranchIDList(trees)
    nBranches = len(branchIDList)

    branchIDLookup = {}
    for i in range(nBranches):
        branchIDLookup[branchIDList[i]] = i

    resultShape = (nTrees, nBranches)

    # Outputs:
    filoTypes = np.full(resultShape, FiloType.ABSENT)
    addedResult = np.full(resultShape, False)
    subtracted = np.full(resultShape, False)
    transitioned = np.full(resultShape, False)
    masterChanged = np.full((nTrees - 1, nBranches), False)
    masterNodes = util.emptyArrayMatrix(nTrees, nBranches)

    for treeIdx, tree in enumerate(trees):
        if trees[treeIdx] is not None and len(trees[treeIdx].branches) > 0: # Skip empty trees
            treeRoot = trees[treeIdx].rootPoint
            if treeRoot is not None:
                for branch in treeRoot.children:
                    branchIdx = branchIDList.index(branch.id)
                    _recursiveFiloTypes(
                        branchIDList, filoTypes, masterNodes, trees, treeIdx, branchIdx,
                        excludeAxon, excludeBasal, terminalDist, filoDist
                    )

    filoExists = (filoTypes > FiloType.ABSENT)
    filos = filoExists & (filoTypes < FiloType.BRANCH_ONLY) # NOTE: brackets needed for numpy precendence
    branches = (filoTypes > FiloType.TERMINAL)
    branchWithFilo = (branches & filos)
    justBranches = (filoTypes == FiloType.BRANCH_ONLY)
    justBranchBefore, justBranchAfter = justBranches[:-1, :], justBranches[1:, :]
    branchWithFiloBefore, branchWithFiloAfter = branchWithFilo[:-1, :], branchWithFilo[1:, :]
    filoBefore, filoAfter = filos[:-1, :], filos[1:, :]
    existBefore, existAfter = filoExists[:-1, :], filoExists[1:, :]
    added = (~existBefore & filoAfter) | (justBranchBefore & branchWithFiloAfter)
    subtracted = (filoBefore & ~existAfter) | (branchWithFiloBefore & justBranchAfter)
    transitioned = filoBefore & ~branches[:-1, :] & branches[1:, :]

    fillMasterChanged(masterChanged, masterNodes)
    added[masterChanged] = False
    subtracted[masterChanged] = False

    return filoTypes, added, subtracted, transitioned, masterChanged, masterNodes

def _recursiveFiloTypes(
    branchIDList: List[str], filoTypes: np.ndarray, masterNodes: np.ndarray,
    trees: List[Tree], treeIdx: int, branchIdx: int,
    excludeAxon: bool, excludeBasal: bool, terminalDist: float, filoDist: float
) -> None:
    branch = trees[treeIdx].getBranchByID(branchIDList[branchIdx])
    if branch is None:
        filoTypes[treeIdx][branchIdx] = FiloType.ABSENT
        return

    pointsWithRoot = branch.points
    if branch.parentPoint is not None:
        pointsWithRoot = [branch.parentPoint] + pointsWithRoot

    # Exclude: 1) empty branches, plus 2) axons and 3) basal dendrites if not needed.
    if branch.isEmpty() or (excludeAxon and branch.isAxon()) or (excludeBasal and branch.isBasal()):
        filoTypes[treeIdx][branchIdx] = FiloType.ABSENT
        return

    # 4) If the branch has a lamella and no children, abort
    if (not branch.hasChildren()) and util.lastPointWithLabelIdx(pointsWithRoot, 'lam') >= 0:
        filoTypes[treeIdx][branchIdx] = FiloType.BRANCH_ONLY
        return

    # Walk down each child in turn:
    totalLength, totalLengthToLastBranch = branch.worldLengths()
    cumulativeLengths = branch.cumulativeWorldLengths()
    forceInterstitial = False
    for pointIdx, point in enumerate(branch.points):
        if len(point.children) == 0:
            continue # Skip childless points

        forceInterstitial = False
        for childBranch in point.children:
            if len(childBranch.points) < 1:
                continue # Skip empty branches

            if childBranch.id not in branchIDList:
                continue # branch is not known? what?

            childBranchIdx = branchIDList.index(childBranch.id)
            childIsFilo, childLength = childBranch.isFilo(filoDist)
            if childIsFilo:
                distPointToEnd = totalLength - cumulativeLengths[pointIdx]
                isTerminal = (distPointToEnd < terminalDist)
                filoTypes[treeIdx][childBranchIdx] = \
                    FiloType.TERMINAL if isTerminal else FiloType.INTERSTITIAL

                # HACK TODO - figure out what this is doing?
                # mark branchtip filopodia as branch:
                # current node has 1 children and is the endpoint
                if len(point.children) == 1 and pointIdx == len(branch.points) - 1:
                    filoTypes[treeIdx][childBranchIdx] = FiloType.BRANCH_ONLY
                    masterNodes[treeIdx][childBranchIdx] = [branchIdx] # we use convention that long branches are their own masternode

            else: # Not filo
                # all terminal filopodia identified so far are actually interstitial
                forceInterstitial = True
                _recursiveFiloTypes(branchIDList, filoTypes, masterNodes, trees, treeIdx, childBranchIdx, excludeAxon, excludeBasal, terminalDist, filoDist)

        # Turn all previous terminal filos into interstitial filos
        if forceInterstitial:
            for prevPointIdx, prevPoint in enumerate(branch.points):
                for childBranch in prevPoint.children:
                    childBranchIdx = childBranch.indexInParent()
                    if filoTypes[treeIdx][childBranchIdx] == FiloType.TERMINAL:
                        filoTypes[treeIdx][childBranchIdx] = FiloType.INTERSTITIAL
                if prevPointIdx == pointIdx:
                    break


    # deal with potential terminal filopodium that's part of the branch
    # {note that forceinterstitial was set for the last child in above section}
    totalDist = totalLength - totalLengthToLastBranch

    # part of this branch is a filopodium
    if totalDist > 0 and totalDist < filoDist:
        #the last child is a branch, so this terminal filo is interstitial
        filoTypes[treeIdx][branchIdx] = \
            FiloType.BRANCH_WITH_INTERSTITIAL if forceInterstitial else FiloType.BRANCH_WITH_TERMINAL

        # branches are also defined by a 'master node' that marks the start of any potential temrinal filopodium
        lastPointWithChildren = None
        for point in reversed(branch.points):
            if len(point.children) > 0:
                lastPointWithChildren = point
                break
        if lastPointWithChildren is not None:
            masterNodes[treeIdx][branchIdx] = [b.indexInParent() for b in lastPointWithChildren.children]

    elif totalDist == 0: # a trunk branch
        # the last node is the masternode
        filoTypes[treeIdx][branchIdx] = FiloType.BRANCH_ONLY
        masterNodes[treeIdx][branchIdx] = [b.indexInParent() for b in branch.points[-1].children]
    else: # a long branch
        # we use convention that long branches are their own masternode
        filoTypes[treeIdx][branchIdx] = FiloType.BRANCH_ONLY
        masterNodes[treeIdx][branchIdx] = [branchIdx]


def fillMasterChanged(masterChanged: np.ndarray, masterNodes: np.ndarray) -> None:
    (nTrees, nBranches) = masterChanged.shape
    for t in range(nTrees):
        for b in range(nBranches):
            l1 = masterNodes[ t ][b]
            l2 = masterNodes[t+1][b]
            masterChanged[t, b] = len(l2) > 0 and len(set(l1) & set(l2)) == 0
