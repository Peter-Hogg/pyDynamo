""" QtImageViewer.py: PyQt image viewer widget for a QPixmap in a QGraphicsView scene with mouse zooming and panning.

"""

import math
import time

from PyQt5.QtCore import Qt, QRectF, pyqtSignal, QT_VERSION_STR
from PyQt5.QtGui import QImage, QPixmap, QPainterPath
from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QFileDialog, QApplication

from pydynamo_brain.util import deltaSz, zStackForUiState
from .dendritePainter import DendritePainter

__author__ = "Marcel Goldschen-Ohm <marcel.goldschen@gmail.com>"
__version__ = '0.9.0'

SINGLE_CLICK_SEC = 0.2
SCROLL_SENSITIVITY = 100.0 # TODO - share with DendriteVolumeCanvas

class QtImageViewer(QGraphicsView):
    """ PyQt image viewer widget for a QPixmap in a QGraphicsView scene with mouse zooming and panning.

    Displays a QImage or QPixmap (QImage is internally converted to a QPixmap).
    To display any other image format, you must first convert it to a QImage or QPixmap.

    Some useful image format conversion utilities:
        qimage2ndarray: NumPy ndarray <==> QImage    (https://github.com/hmeine/qimage2ndarray)
        ImageQt: PIL Image <==> QImage  (https://github.com/python-pillow/Pillow/blob/master/PIL/ImageQt.py)

    Mouse interaction:
        Left mouse button drag: Pan image.
        Right mouse button drag: Zoom box.
        Right mouse button doubleclick: Zoom to show entire image.
    """

    # Mouse button signals emit image scene (x, y) coordinates.
    # !!! For image (row, column) matrix indexing, row = y and column = x.
    leftMouseButtonPressed = pyqtSignal(float, float)
    rightMouseButtonPressed = pyqtSignal(float, float)
    leftMouseButtonReleased = pyqtSignal(float, float)
    rightMouseButtonReleased = pyqtSignal(float, float)
    leftMouseButtonDoubleClicked = pyqtSignal(float, float)
    rightMouseButtonDoubleClicked = pyqtSignal(float, float)

    def __init__(self, parentView, imageData=None):
        QGraphicsView.__init__(self)
        self.parentView = parentView

        # Image is displayed as a QPixmap in a QGraphicsScene attached to this QGraphicsView.
        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # Store a local handle to the scene's current image pixmap.
        self._pixmapHandle = None

        # Image aspect ratio mode.
        # !!! ONLY applies to full image. Aspect ratio is always ignored when zooming.
        #   Qt.IgnoreAspectRatio: Scale image to fit viewport.
        #   Qt.KeepAspectRatio: Scale image to fit inside viewport, preserving aspect ratio.
        #   Qt.KeepAspectRatioByExpanding: Scale image to fill the viewport, preserving aspect ratio.
        self.aspectRatioMode = Qt.KeepAspectRatio

        # Scroll bar behaviour.
        #   Qt.ScrollBarAlwaysOff: Never shows a scroll bar.
        #   Qt.ScrollBarAlwaysOn: Always shows a scroll bar.
        #   Qt.ScrollBarAsNeeded: Shows a scroll bar only when zoomed.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # Flags for enabling/disabling mouse interaction.
        self.canZoom = True
        self.canPan = True

        # HACK - mouse click vs drag disambiguation
        self.lastMousePressSec = -1
        self.lastMousePressPos = None

        # HACK - ignore moving view twice when local change gets sent global, or initial zoom.
        self.ignoreScrollChange = False
        self.ignoreGlobalMoveViewRect = False
        self.onlyPerformLocalViewRect = False

        if imageData is not None:
            self.setImage(imageData)

        self.horizontalScrollBar().valueChanged.connect(self.viewportChangedByScroll)
        self.verticalScrollBar().valueChanged.connect(self.viewportChangedByScroll)
        self.setMouseTracking(True)

    def hasImage(self):
        """ Returns whether or not the scene contains an image pixmap.
        """
        return self._pixmapHandle is not None

    def clearImage(self):
        """ Removes the current image pixmap from the scene if it exists.
        """
        if self.hasImage():
            self.scene.removeItem(self._pixmapHandle)
            self._pixmapHandle = None

    def pixmap(self):
        """ Returns the scene's current image pixmap as a QPixmap, or else None if no image exists.
        :rtype: QPixmap | None
        """
        if self.hasImage():
            return self._pixmapHandle.pixmap()
        return None

    def image(self):
        """ Returns the scene's current image pixmap as a QImage, or else None if no image exists.
        :rtype: QImage | None
        """
        if self.hasImage():
            return self._pixmapHandle.pixmap().toImage()
        return None

    def setImage(self, image, maintainZoom=False):
        """ Set the scene's current image pixmap to the input QImage or QPixmap.
        Raises a RuntimeError if the input image has type other than QImage or QPixmap.
        :type image: QImage | QPixmap
        """
        if type(image) is QPixmap:
            pixmap = image
        elif type(image) is QImage:
            pixmap = QPixmap.fromImage(image)
        else:
            raise RuntimeError("ImageViewer.setImage: Argument must be a QImage or QPixmap.")
        if self.hasImage():
            self._pixmapHandle.setPixmap(pixmap)
        else:
            self._pixmapHandle = self.scene.addPixmap(pixmap)
        self.setSceneRect(QRectF(pixmap.rect()))  # Set scene size to image size.
        self.forceRepaint()

    def forceRepaint(self):
        """ Show current zoom (if showing entire image, apply current aspect ratio mode).
        """
        if not self.hasImage():
            return
        self.viewport().update()

    def resizeEvent(self, event):
        """ Maintain current zoom on resize.
        """
        self.forceRepaint()
        self.onlyPerformLocalViewRect = True
        self.zoom(0) # Force image to fit, but only in this screen.
        self.onlyPerformLocalViewRect = False
        # Note: This means if you slowly resize, it'll gradually zoom out. Not idea, but ok?

    def mouseMoveEvent(self, event):
        QGraphicsView.mouseMoveEvent(self, event)

        fullState = self.parentView.uiState.parent()
        scenePos = self.mapToScene(event.pos())
        zAt = zStackForUiState(self.parentView.uiState) * 1.0
        location = (scenePos.x(), scenePos.y(), zAt)

        circleOver = None
        if self.parentView.uiState.parent().inPunctaMode():
            circleOver = self.parentView.punctaOnPixel(location)
        else:
            circleOver = self.parentView.pointOnPixel(location)
        self.viewport().setCursor(Qt.OpenHandCursor if circleOver is not None else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        """ Start mouse pan or zoom mode.
        """
        self.lastMousePressSec = time.time()
        self.lastMousePressPos = event.pos()

        scenePos = self.mapToScene(event.pos())
        if event.button() == Qt.LeftButton:
            if self.canPan:
                self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.leftMouseButtonPressed.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.RightButton:
            if self.canZoom:
                self.setDragMode(QGraphicsView.RubberBandDrag)
            self.rightMouseButtonPressed.emit(scenePos.x(), scenePos.y())
        QGraphicsView.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        """ Stop mouse pan or zoom mode (apply zoom if valid).
        """
        timeDiff = time.time() - self.lastMousePressSec
        if timeDiff < SINGLE_CLICK_SEC: # TODO - check distance
            scenePos = self.mapToScene(event.pos())
            self.parentView.mouseClickEvent(event, scenePos)
            QGraphicsView.mouseReleaseEvent(self, event)
            return

        QGraphicsView.mouseReleaseEvent(self, event)
        scenePos = self.mapToScene(event.pos())
        if event.button() == Qt.LeftButton:
            self.setDragMode(QGraphicsView.NoDrag)
            self.leftMouseButtonReleased.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.RightButton:
            if self.canZoom:
                selectionBBox = self.scene.selectionArea().boundingRect()
                self.scene.setSelectionArea(QPainterPath())  # Clear current selection area.
                if selectionBBox.isValid():
                    self.moveViewRect(selectionBBox)
                    self.forceRepaint()
            self.setDragMode(QGraphicsView.NoDrag)
            self.rightMouseButtonReleased.emit(scenePos.x(), scenePos.y())

    def mouseDoubleClickEvent(self, event):
        """ Show entire image.
        """
        scenePos = self.mapToScene(event.pos())
        if event.button() == Qt.LeftButton:
            self.leftMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
        elif event.button() == Qt.RightButton:
            if self.canZoom:
                self.moveViewRect(self.sceneRect())
            self.rightMouseButtonDoubleClicked.emit(scenePos.x(), scenePos.y())
        QGraphicsView.mouseDoubleClickEvent(self, event)

    def wheelEvent(self, event):
        # Shift-scroll = zoom in/out of image.
        # Without shift (i.e. normal scroll) handled by DendriteVolumeCanvas
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            self.handleZoomScroll(event.angleDelta().y())
            event.accept()

    def handleZoomScroll(self, yDelta):
        self.zoom(-yDelta / SCROLL_SENSITIVITY)

    def zoom(self, logAmount):
        scale = math.exp(logAmount)
        border = self.getViewportRect()
        mid = border.center()

        border.translate(-mid)
        border = QRectF(border.topLeft() * scale, border.bottomRight() * scale)
        border.translate(mid)
        self.moveViewRect(border.intersected(self.sceneRect()))

    def moveViewRect(self, newViewRect, alreadySetFromScroll=False):
        self.ignoreGlobalMoveViewRect = True
        if not alreadySetFromScroll:
            self.fitInView(newViewRect, self.aspectRatioMode) # Only set locally if not done already...
        if not self.onlyPerformLocalViewRect:
            self.parentView.dynamoWindow.handleDendriteMoveViewRect(newViewRect, self.parentView.stackWindow)
        self.ignoreGlobalMoveViewRect = False

    def handleGlobalMoveViewRect(self, newViewRect):
        if self.ignoreGlobalMoveViewRect:
            return
        self.ignoreScrollChange = True
        self.fitInView(newViewRect, self.aspectRatioMode)
        self.forceRepaint()
        self.ignoreScrollChange = False

    def viewportChangedByScroll(self, event):
        if self.ignoreScrollChange:
            return
        self.moveViewRect(self.getViewportRect(), alreadySetFromScroll=True)

    def getViewportRect(self):
        return self.mapToScene(self.viewport().geometry()).boundingRect()

    def toSceneDist(self, pixelDistX, pixelDistY):
        mappedA = self.mapToScene(0, 0)
        mappedB = self.mapToScene(int(pixelDistX), int(pixelDistY))
        dX, dY = mappedB.x() - mappedA.x(), mappedB.y() - mappedA.y()
        return dX, dY

    # invert toSceneDist
    def fromSceneDist(self, sceneDistX, sceneDistY):
        # toSceneDist(1, 1) = x, y
        # => toSceneDist(sdX, sdY) = sdX * x, sdY * y
        # => toSceneDist(sdX/x, sdY/y) = sdX, sdY
        x, y = self.toSceneDist(1, 1)
        return sceneDistX / x, sceneDistY / y

    def sceneDimension(self):
        viewRect = self.getViewportRect()
        return self.toSceneDist(viewRect.width(), viewRect.height())
