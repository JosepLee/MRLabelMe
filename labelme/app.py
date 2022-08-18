# -*- coding: utf-8 -*-

from fileinput import filename
import functools
import html
import json
import math
import os
import os.path as osp
import re
import webbrowser
import numpy as np
from PIL import Image

import imgviz
import natsort
import cv2
from qtpy import QtCore
from qtpy.QtCore import Qt
from qtpy import QtGui
from qtpy import QtWidgets

from labelme import __appname__
from labelme import PY2


from . import utils
from labelme.config import get_config
from labelme.label_file import LabelFile
from labelme.label_file import LabelFileError
from labelme.logger import logger
from labelme.shape import Shape
from labelme.widgets import BrightnessContrastDialog
from labelme.widgets import Canvas
from labelme.widgets import FileDialogPreview
from labelme.widgets import LabelDialog
from labelme.widgets import LabelListWidget
from labelme.widgets import LabelListWidgetItem
from labelme.widgets import ToolBar
from labelme.widgets import UniqueLabelQListWidget
from labelme.widgets import ZoomWidget
from labelme.widgets import PatientInfo
# FIXME
# - [medium] Set max zoom value to something big enough for FitWidth/Window

# TODO(unknown):
# - Zoom is too "steppy".


LABEL_COLORMAP = imgviz.label_colormap()


#MainWindow类，是labelme的主窗口
class MainWindow(QtWidgets.QMainWindow):

    #控制缩放模式的字典变量，参考self.scaler
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = 0, 1, 2

    #类构造函数，输入参数config，filename，output，output_file,output_dir,都来自与运行初始化参数
    def __init__(
        self,
        config=None,
        filename=None,
        output=None,
        output_file=None,
        output_dir=None,
    ):
        if output is not None:
            logger.warning(
                "argument output is deprecated, use output_file instead"
            )
            if output_file is None:
                output_file = output

        # see labelme/config/default_config.yaml for valid configuration
        if config is None:
            config = get_config()
        self._config = config
        self.nowFocus='RGB'
        # set default shape colors
        Shape.line_color = QtGui.QColor(*self._config["shape"]["line_color"])
        Shape.fill_color = QtGui.QColor(*self._config["shape"]["fill_color"])
        Shape.select_line_color = QtGui.QColor(
            *self._config["shape"]["select_line_color"]
        )
        Shape.select_fill_color = QtGui.QColor(
            *self._config["shape"]["select_fill_color"]
        )
        Shape.vertex_fill_color = QtGui.QColor(
            *self._config["shape"]["vertex_fill_color"]
        )
        Shape.hvertex_fill_color = QtGui.QColor(
            *self._config["shape"]["hvertex_fill_color"]
        )

        # Set point size from config file
        Shape.point_size = self._config["shape"]["point_size"]

        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__)

        # Whether we need to save or not.
        self.dirty = False

        self._noSelectionSlot = False

        self._copied_shapes = None
        self.saveMode='Both'
        # Main widgets and related state.
        #指向另一个文件，此类实例化的应该是主要窗口部件
        # widgets意思是窗口小部件
        self.labelDialog = LabelDialog(
            parent=self,
            labels=self._config["labels"],
            sort_labels=self._config["sort_labels"],
            show_text_field=self._config["show_label_text_field"],
            completion=self._config["label_completion"],
            fit_to_content=self._config["fit_to_content"],
            flags=self._config["label_flags"],
        )

        #初始化labellist小部件，label list对应的是右边的一个小窗体
        self.labelListColor = LabelListWidget()
        self.labelListDepth = LabelListWidget()
        #看名称应该是上一个打开的目录
        self.lastOpenDir = None

        #和flag有关的一系列部件设置，flag功能存疑
        self.flag_dock = self.flag_widget = None
        self.flag_dock = QtWidgets.QDockWidget(self.tr("Flags"), self)
        self.flag_dock.setObjectName("Flags")
        self.flag_widget = QtWidgets.QListWidget()
        if config["flags"]:
            self.loadFlags({k: False for k in config["flags"]})
        self.flag_dock.setWidget(self.flag_widget)
        self.flag_widget.itemChanged.connect(self.setDirty)

        #labellist相关参数
        self.labelListColor.itemSelectionChanged.connect(self.labelSelectionChangedRGB)

        self.labelListColor.itemDoubleClicked.connect(self.editLabel)#editlabel是双击事件，双击编辑label，labellist是dock元件之一

        self.labelListColor.itemChanged.connect(self.labelItemChangedRGB)

        self.labelListColor.itemDropped.connect(self.labelOrderChangedRGB)

        self.labelListDepth.itemSelectionChanged.connect(self.labelSelectionChangedDepth)

        self.labelListDepth.itemDoubleClicked.connect(self.editLabel)#editlabel是双击事件，双击编辑label，labellist是dock元件之一

        self.labelListDepth.itemChanged.connect(self.labelItemChangedDepth)

        self.labelListDepth.itemDropped.connect(self.labelOrderChangedDepth)

        #dock相关参数，dock是什么？dock是围绕在主窗口周围的小部件的名称：英文dock：码头，停靠
        self.shape_dockColor = QtWidgets.QDockWidget(
            self.tr("RGB Polygon Labels"), self
        )
        self.shape_dockColor.setObjectName("Labels")
        self.shape_dockColor.setWidget(self.labelListColor)


        self.shape_dockDepth = QtWidgets.QDockWidget(
            self.tr("Depth Polygon Labels"), self
        )
        self.shape_dockDepth.setObjectName("Labels")
        self.shape_dockDepth.setWidget(self.labelListDepth)

        self.uniqLabelList = UniqueLabelQListWidget()
        self.uniqLabelList.setToolTip(
            self.tr(
                "Select label to start annotating for it. "
                "Press 'Esc' to deselect."
            )
        )

        if self._config["labels"]:
            for label in self._config["labels"]:
                item = self.uniqLabelList.createItemFromLabel(label)
                self.uniqLabelList.addItem(item)
                rgb = self._get_rgb_by_label(label)
                self.uniqLabelList.setItemLabel(item, label, rgb)

        #label list dock组件注册
        self.label_dock = QtWidgets.QDockWidget(self.tr("Label List"), self)
        self.label_dock.setObjectName("Label List")
        self.label_dock.setWidget(self.uniqLabelList)

        self.fileSearch = QtWidgets.QLineEdit()
        self.fileSearch.setPlaceholderText(self.tr("Search Filename"))
        self.fileSearch.textChanged.connect(self.fileSearchChanged)
        self.fileListWidget = QtWidgets.QListWidget()
        self.fileListWidget.itemSelectionChanged.connect(
            self.fileSelectionChanged
        )
        fileListLayout = QtWidgets.QVBoxLayout()
        fileListLayout.setContentsMargins(0, 0, 0, 0)
        fileListLayout.setSpacing(0)
        fileListLayout.addWidget(self.fileSearch)
        fileListLayout.addWidget(self.fileListWidget)
        self.file_dock = QtWidgets.QDockWidget(self.tr("File List"), self)
        self.file_dock.setObjectName("Files")
        fileListWidget = QtWidgets.QWidget()
        fileListWidget.setLayout(fileListLayout)
        self.file_dock.setWidget(fileListWidget)

        self.zoomWidget = ZoomWidget()
        self.setAcceptDrops(True)


        #FunctionPannel,就是画布底下的按钮部分
        funcPanLayout = QtWidgets.QHBoxLayout()
        funcPanLayout.setContentsMargins(0, 0, 0, 0)
        funcPanLayout.setSpacing(0)
        funcPanLayout.addWidget(QtWidgets.QPushButton("Detect KeyPoint"))
        #TODO Copy All Label要想办法写出来
        copyLabels=QtWidgets.QPushButton("Copy All Points")
        copyLabels.clicked.connect(self.copyAllShapes)
        copyLabels.setCheckable(True)
        funcPanLayout.addWidget(copyLabels)
        self.functionPannelWidget = QtWidgets.QWidget()
        self.functionPannelWidget.setLayout(funcPanLayout)


        #PatientInfo Dock
        #TODO Info Dock组件要写出来
        self.info_dock = QtWidgets.QDockWidget(self.tr("Patient Info"), self)
        self.info_dock.setObjectName("Patient Info")
        self.patientINFO=PatientInfo.PatientInfoWidget()
        patientInfoWidget = self.patientINFO.PatientInfoDock()

        self.info_dock.setWidget(patientInfoWidget)


        #canvasLeft，画布，帆布：对应的是整个界面还是说图片？
        self.canvasLeft = self.labelListColor.canvas = Canvas(
            epsilon=self._config["epsilon"],
            double_click=self._config["canvasLeft"]["double_click"],
            num_backups=self._config["canvasLeft"]["num_backups"],
        )

        #TODO Canvas2的功能只有显示，没有标注，看看怎么从canvas继承还是重写
        self.canvasRight = self.labelListDepth.canvas = Canvas(
            epsilon=self._config["epsilon"],
            double_click=self._config["canvasRight"]["double_click"],
            num_backups=self._config["canvasRight"]["num_backups"],
        )
        self.canvasLeft.zoomRequest.connect(self.zoomRequest)
        self.canvasRight.zoomRequest.connect(self.zoomRequest)
        #Qt.Vertical
        splitArea = QtWidgets.QSplitter(Qt.Vertical)
        splitArea_canvas = QtWidgets.QSplitter(Qt.Vertical)
        # scrollArea = QtWidgets.QScrollArea()
        # scrollArea.setWidget(self.canvasLeft)
        # scrollArea.setWidgetResizable(True)
        # self.scrollBars = {
        #     Qt.Vertical: scrollArea.verticalScrollBar(),
        #     Qt.Horizontal: scrollArea.horizontalScrollBar(),
        # }
        self.canvasLeft.scrollRequest.connect(self.scrollRequest)

        self.canvasLeft.newShape.connect(self.newShapeRGB)
        self.canvasLeft.shapeMoved.connect(self.setDirty)

        self.canvasLeft.selectionChanged.connect(self.shapeSelectionChangedColor)
        self.canvasLeft.focusChanged.connect(self.focusChangedColor)
        self.canvasLeft.drawingPolygon.connect(self.toggleDrawingSensitive)

        #Canvas2是深度画布
        self.canvasRight.scrollRequest.connect(self.scrollRequest)

        self.canvasRight.newShape.connect(self.newShapeDepth)
        self.canvasRight.shapeMoved.connect(self.setDirty)
        self.canvasRight.selectionChanged.connect(self.shapeSelectionChangedDepth)
        self.canvasRight.focusChanged.connect(self.focusChangedDepth)
        self.canvasRight.drawingPolygon.connect(self.toggleDrawingSensitive)
        # self.setCentralWidget(scrollArea)

        # uniLabelList
        self.uniqLabelList.currentItemChanged.connect(self.itemChangedUniqLabelList)

        scrollArea1 = QtWidgets.QScrollArea()
        scrollArea1.setWidget(self.canvasLeft)
        scrollArea1.setWidgetResizable(True)
        self.scrollBars = {
            Qt.Vertical: scrollArea1.verticalScrollBar(),
            Qt.Horizontal: scrollArea1.horizontalScrollBar(),
        }

        scrollArea2 = QtWidgets.QScrollArea()
        scrollArea2.setWidget(self.canvasRight)
        scrollArea2.setWidgetResizable(True)
        self.scrollBars2 = {
            Qt.Vertical: scrollArea2.verticalScrollBar(),
            Qt.Horizontal: scrollArea2.horizontalScrollBar(),
        }


        #先把主窗口分成上下两个区域
        splitArea.addWidget(splitArea_canvas)
        splitArea.addWidget(self.functionPannelWidget)
        #这个要改一下和窗口挂钩的比例，写死会不会有bug
        # TODO(LZX): 调整窗口比例
        splitArea.setSizes([400, 1])

        #再把画布区域分成两个窗口
        splitArea_canvas.addWidget(scrollArea1)
        splitArea_canvas.addWidget(scrollArea2)

        self.setCentralWidget(splitArea)


        #这块加入了四个dock，同时再加入dock应该就是从这里加入
        features = QtWidgets.QDockWidget.DockWidgetFeatures()
        for dock in ["flag_dock", "label_dock", "shape_dockColor","shape_dockDepth", "file_dock", "info_dock"]:
            if self._config[dock]["closable"]:
                features = features | QtWidgets.QDockWidget.DockWidgetClosable
            if self._config[dock]["floatable"]:
                features = features | QtWidgets.QDockWidget.DockWidgetFloatable
            if self._config[dock]["movable"]:
                features = features | QtWidgets.QDockWidget.DockWidgetMovable
            getattr(self, dock).setFeatures(features)
            if self._config[dock]["show"] is False:
                getattr(self, dock).setVisible(False)


        #给dock指定位置
        self.addDockWidget(Qt.RightDockWidgetArea, self.info_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.flag_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.label_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.shape_dockColor)
        self.addDockWidget(Qt.RightDockWidgetArea, self.shape_dockDepth)
        self.addDockWidget(Qt.RightDockWidgetArea, self.file_dock)


        # Actions
        #Actions的相关代码，调用action函数把很多的功能给实例化，atcion函数功能未知
        #这些action对应主窗口上下拉菜单的所有选项
        # partial函数重用调用newAction函数，newAction函数是封装好的Qt函数
        #通过qt.py中的函数注册出这些按钮
        action = functools.partial(utils.newAction, self)
        shortcuts = self._config["shortcuts"]
        quit = action(
            self.tr("&Quit"),#这个tr是国际化的东西，用来翻译语言的，会自动翻译
            self.close,
            shortcuts["quit"],
            "quit",
            self.tr("Quit application"),
        )
        #TODO 加入按钮还要加入功能，同时确定按钮好不好用,看看open对应的函数是怎么写的
        #openRGB只显示在左边，depth显示在右边，both都显示
        open = action(
            self.tr("&Open"),
            self.openFile,
            shortcuts["open"],
            "open",
            self.tr("Open image"),
        )
        # openBoth_ = action(
        #     self.tr("&Open Both"),
        #     self.openBoth,
        #     shortcuts["open_Both"],
        #     "open",
        #     self.tr("&Open both RGB&depth"),
        # )
        opendir = action(
            self.tr("&Open Dir"),
            self.openDirDialog,
            shortcuts["open_dir"],
            "open",
            self.tr("Open Dir"),
        )
        openNextImg = action(
            self.tr("&Next Image"),
            self.openNextImg,
            shortcuts["open_next"],
            "next",
            self.tr("Open next (hold Ctl+Shift to copy labels)"),
            enabled=False,
        )
        openPrevImg = action(
            self.tr("&Prev Image"),
            self.openPrevImg,
            shortcuts["open_prev"],
            "prev",
            self.tr("Open prev (hold Ctl+Shift to copy labels)"),
            enabled=False,
        )
        save = action(
            self.tr("&Save"),
            self.saveFile,
            shortcuts["save"],
            "save",
            self.tr("Save labels to file"),
            enabled=False,
        )
        saveAs = action(
            self.tr("&Save As"),
            self.saveFileAs,
            shortcuts["save_as"],
            "save-as",
            self.tr("Save labels to a different file"),
            enabled=False,
        )

        deleteFile = action(
            self.tr("&Delete File"),
            self.deleteFile,
            shortcuts["delete_file"],
            "delete",
            self.tr("Delete current label file"),
            enabled=False,
        )

        changeOutputDir = action(
            self.tr("&Change Output Dir"),
            slot=self.changeOutputDirDialog,
            shortcut=shortcuts["save_to"],
            icon="open",
            tip=self.tr("Change where annotations are loaded/saved"),
        )

        saveAuto = action(
            text=self.tr("Save &Automatically"),
            slot=lambda x: self.actions.saveAuto.setChecked(x),
            icon="save",
            tip=self.tr("Save automatically"),
            checkable=True,
            enabled=True,
        )
        saveAuto.setChecked(self._config["auto_save"])

        saveWithImageData = action(
            text="Save With Image Data",
            slot=self.enableSaveImageWithData,
            tip="Save image data in label file",
            checkable=True,
            checked=self._config["store_data"],
        )

        close = action(
            "&Close",
            self.closeFile,
            shortcuts["close"],
            "close",
            "Close current file",
        )

        toggle_keep_prev_mode = action(
            self.tr("Keep Previous Annotation"),
            self.toggleKeepPrevMode,
            shortcuts["toggle_keep_prev_mode"],
            None,
            self.tr('Toggle "keep pevious annotation" mode'),
            checkable=True,
        )
        toggle_keep_prev_mode.setChecked(self._config["keep_prev"])

        createMode = action(
            self.tr("Create Polygons"),
            lambda: self.toggleDrawMode(False, createMode="point"),
            shortcuts["create_polygon"],
            "objects",
            self.tr("Start drawing polygons"),
            enabled=False,
        )
        createRectangleMode = action(
            self.tr("Create Rectangle"),
            lambda: self.toggleDrawMode(False, createMode="rectangle"),
            shortcuts["create_rectangle"],
            "objects",
            self.tr("Start drawing rectangles"),
            enabled=False,
        )
        createCircleMode = action(
            self.tr("Create Circle"),
            lambda: self.toggleDrawMode(False, createMode="circle"),
            shortcuts["create_circle"],
            "objects",
            self.tr("Start drawing circles"),
            enabled=False,
        )
        createLineMode = action(
            self.tr("Create Line"),
            lambda: self.toggleDrawMode(False, createMode="line"),
            shortcuts["create_line"],
            "objects",
            self.tr("Start drawing lines"),
            enabled=False,
        )
        createPointMode = action(
            self.tr("Create Point"),
            lambda: self.toggleDrawMode(False, createMode="point"),
            shortcuts["create_point"],
            "objects",
            self.tr("Start drawing points"),
            enabled=False,
        )
        createLineStripMode = action(
            self.tr("Create LineStrip"),
            lambda: self.toggleDrawMode(False, createMode="linestrip"),
            shortcuts["create_linestrip"],
            "objects",
            self.tr("Start drawing linestrip. Ctrl+LeftClick ends creation."),
            enabled=False,
        )
        editMode = action(
            self.tr("Edit Polygons"),
            self.setEditMode,
            shortcuts["edit_polygon"],
            "edit",
            self.tr("Move and edit the selected polygons"),
            enabled=False,
        )

        delete = action(
            self.tr("Delete Polygons"),
            self.deleteSelectedShape,
            shortcuts["delete_polygon"],
            "cancel",
            self.tr("Delete the selected polygons"),
            enabled=False,
        )
        duplicate = action(
            self.tr("Duplicate Polygons"),
            self.duplicateSelectedShape,
            shortcuts["duplicate_polygon"],
            "copy",
            self.tr("Create a duplicate of the selected polygons"),
            enabled=False,
        )
        sync = action(
            self.tr("sync Polygons"),
            self.transferSelectedShape,
            shortcuts["Sync_polygon"],
            "copy",
            self.tr("Create a copy of the selected polygons to another canvas"),
            enabled=False,
        )
        copy = action(
            self.tr("Copy Polygons"),
            self.copySelectedShape,
            shortcuts["copy_polygon"],
            "copy_clipboard",
            self.tr("Copy selected polygons to clipboard"),
            enabled=False,
        )
        paste = action(
            self.tr("Paste Polygons"),
            self.pasteSelectedShape,
            shortcuts["paste_polygon"],
            "paste",
            self.tr("Paste copied polygons"),
            enabled=False,
        )
        undoLastPoint = action(
            self.tr("Undo last point"),
            self.canvasLeft.undoLastPoint,
            shortcuts["undo_last_point"],
            "undo",
            self.tr("Undo last drawn point"),
            enabled=False,
        )
        removePoint = action(
            text="Remove Selected Point",
            slot=self.removeSelectedPoint,
            shortcut=shortcuts["remove_selected_point"],
            icon="edit",
            tip="Remove selected point from polygon",
            enabled=False,
        )

        undo = action(
            self.tr("Undo"),
            self.undoShapeEdit,
            shortcuts["undo"],
            "undo",
            self.tr("Undo last add and edit of shape"),
            enabled=False,
        )

        hideAll = action(
            self.tr("&Hide\nPolygons"),
            functools.partial(self.togglePolygons, False),
            icon="eye",
            tip=self.tr("Hide all polygons"),
            enabled=False,
        )
        showAll = action(
            self.tr("&Show\nPolygons"),
            functools.partial(self.togglePolygons, True),
            icon="eye",
            tip=self.tr("Show all polygons"),
            enabled=False,
        )

        help = action(
            self.tr("&Tutorial"),
            self.tutorial,
            icon="help",
            tip=self.tr("Show tutorial page"),
        )

        zoom = QtWidgets.QWidgetAction(self)
        zoom.setDefaultWidget(self.zoomWidget)
        self.zoomWidget.setWhatsThis(
            str(
                self.tr(
                    "Zoom in or out of the image. Also accessible with "
                    "{} and {} from the canvasLeft."
                )
            ).format(
                utils.fmtShortcut(
                    "{},{}".format(shortcuts["zoom_in"], shortcuts["zoom_out"])
                ),
                utils.fmtShortcut(self.tr("Ctrl+Wheel")),
            )
        )
        self.zoomWidget.setEnabled(False)

        zoomIn = action(
            self.tr("Zoom &In"),
            functools.partial(self.addZoom, 1.1),
            shortcuts["zoom_in"],
            "zoom-in",
            self.tr("Increase zoom level"),
            enabled=False,
        )
        zoomOut = action(
            self.tr("&Zoom Out"),
            functools.partial(self.addZoom, 0.9),
            shortcuts["zoom_out"],
            "zoom-out",
            self.tr("Decrease zoom level"),
            enabled=False,
        )
        zoomOrg = action(
            self.tr("&Original size"),
            functools.partial(self.setZoom, 100),
            shortcuts["zoom_to_original"],
            "zoom",
            self.tr("Zoom to original size"),
            enabled=False,
        )
        keepPrevScale = action(
            self.tr("&Keep Previous Scale"),
            self.enableKeepPrevScale,
            tip=self.tr("Keep previous zoom scale"),
            checkable=True,
            checked=self._config["keep_prev_scale"],
            enabled=True,
        )
        fitWindow = action(
            self.tr("&Fit Window"),
            self.setFitWindow,
            shortcuts["fit_window"],
            "fit-window",
            self.tr("Zoom follows window size"),
            checkable=True,
            enabled=False,
        )
        fitWidth = action(
            self.tr("Fit &Width"),
            self.setFitWidth,
            shortcuts["fit_width"],
            "fit-width",
            self.tr("Zoom follows window width"),
            checkable=True,
            enabled=False,
        )
        brightnessContrast = action(
            "&Brightness Contrast",
            self.brightnessContrast,
            None,
            "color",
            "Adjust brightness and contrast",
            enabled=False,
        )

        # Group zoom controls into a list for easier toggling.
        #把zoom的相关控制给编组，括号内容是元组
        zoomActions = (
            self.zoomWidget,
            zoomIn,
            zoomOut,
            zoomOrg,
            fitWindow,
            fitWidth,
        )
        self.zoomMode = self.FIT_WINDOW
        fitWindow.setChecked(Qt.Checked)
        self.scalers = {
            self.FIT_WINDOW: self.scaleFitWindow,
            self.FIT_WIDTH: self.scaleFitWidth,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 0.71,
        }

        edit = action(
            self.tr("&Edit Label"),
            self.editLabel,#在edit情况下，激活editlabel，在create情况下不能编辑label
            shortcuts["edit_label"],
            "edit",
            self.tr("Modify the label of the selected polygon"),
            enabled=False,
        )

        fill_drawing = action(
            self.tr("Fill Drawing Polygon"),
            self.canvasLeft.setFillDrawing,
            None,
            "color",
            self.tr("Fill polygon while drawing"),
            checkable=True,
            enabled=True,
        )
        fill_drawing.trigger()

        # Lavel list context menu.
        #形成了QMenu对象，把label相关做成menu
        labelMenu = QtWidgets.QMenu()
        utils.addActions(labelMenu, (edit, delete))
        self.labelListColor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.labelListColor.customContextMenuRequested.connect(
            self.popLabelListColorMenu
        )

        self.labelListDepth.setContextMenuPolicy(Qt.CustomContextMenu)
        self.labelListDepth.customContextMenuRequested.connect(
            self.popLabelListDepthMenu
        )

        # Store actions for further handling.
        self.actions = utils.struct(
            saveAuto=saveAuto,
            saveWithImageData=saveWithImageData,
            changeOutputDir=changeOutputDir,
            save=save,
            saveAs=saveAs,
            open=open,
            # openBoth=openBoth_,
            close=close,
            deleteFile=deleteFile,
            toggleKeepPrevMode=toggle_keep_prev_mode,
            delete=delete,
            edit=edit,
            duplicate=duplicate,
            sync=sync,
            copy=copy,
            paste=paste,
            undoLastPoint=undoLastPoint,
            undo=undo,
            removePoint=removePoint,
            createMode=createMode,
            editMode=editMode,
            createRectangleMode=createRectangleMode,
            createCircleMode=createCircleMode,
            createLineMode=createLineMode,
            createPointMode=createPointMode,
            createLineStripMode=createLineStripMode,
            zoom=zoom,
            zoomIn=zoomIn,
            zoomOut=zoomOut,
            zoomOrg=zoomOrg,
            keepPrevScale=keepPrevScale,
            fitWindow=fitWindow,
            fitWidth=fitWidth,
            brightnessContrast=brightnessContrast,
            zoomActions=zoomActions,
            openNextImg=openNextImg,
            openPrevImg=openPrevImg,
            # fileMenuActions=(open,openBoth_, opendir, save, saveAs, close, quit),
            fileMenuActions=(open, opendir, save, saveAs, close, quit),
            tool=(),
            # XXX: need to add some actions here to activate the shortcut
            editMenu=(
                edit,
                duplicate,
                sync,
                delete,
                None,
                undo,
                undoLastPoint,
                None,
                removePoint,
                None,
                toggle_keep_prev_mode,
            ),
            # menu shown at right click
            menu=(
                createMode,
                createRectangleMode,
                createCircleMode,
                createLineMode,
                createPointMode,
                createLineStripMode,
                editMode,
                edit,
                duplicate,
                sync,
                copy,
                paste,
                delete,
                undo,
                undoLastPoint,
                removePoint,
            ),
            onLoadActive=(
                close,
                createMode,
                createRectangleMode,
                createCircleMode,
                createLineMode,
                createPointMode,
                createLineStripMode,
                editMode,
                brightnessContrast,
            ),
            onShapesPresent=(saveAs, hideAll, showAll),
        )

        self.canvasLeft.vertexSelected.connect(self.actions.removePoint.setEnabled)

        self.menus = utils.struct(
            file=self.menu(self.tr("&File")),
            edit=self.menu(self.tr("&Edit")),
            view=self.menu(self.tr("&View")),
            help=self.menu(self.tr("&Help")),
            recentFiles=QtWidgets.QMenu(self.tr("Open &Recent")),
            labelList=labelMenu,
        )

        utils.addActions(
            self.menus.file,
            (
                open,
                # openBoth_,
                openNextImg,
                openPrevImg,
                opendir,
                self.menus.recentFiles,
                save,
                saveAs,
                saveAuto,
                changeOutputDir,
                saveWithImageData,
                close,
                deleteFile,
                None,
                quit,
            ),
        )
        utils.addActions(self.menus.help, (help,))
        utils.addActions(
            self.menus.view,
            (
                self.flag_dock.toggleViewAction(),
                self.label_dock.toggleViewAction(),
                self.shape_dockColor.toggleViewAction(),
                self.shape_dockDepth.toggleViewAction(),
                self.file_dock.toggleViewAction(),
                None,
                fill_drawing,
                None,
                hideAll,
                showAll,
                None,
                zoomIn,
                zoomOut,
                zoomOrg,
                keepPrevScale,
                None,
                fitWindow,
                fitWidth,
                None,
                brightnessContrast,
            ),
        )

        self.menus.file.aboutToShow.connect(self.updateFileMenu)

        # Custom context menu for the canvasLeft widget:
        utils.addActions(self.canvasLeft.menus[0], self.actions.menu)
        utils.addActions(
            self.canvasLeft.menus[1],
            (
                action("&Copy here", self.copyShape),
                action("&Move here", self.moveShape),
            ),
        )

        #这个是左边的工具栏，至于里边的按钮是怎么封装的，可以层层递进去看
        # 按钮应该就是按照action函数封装的，只不过不同的action装到了不同的地方
        self.tools = self.toolbar("Tools")
        # Menu buttons on Left
        self.actions.tool = (
            open,
            # openBoth_,
            opendir,
            openNextImg,
            openPrevImg,
            save,
            deleteFile,
            None,
            createMode,
            editMode,
            # duplicate,
            sync,
            # copy,
            # paste,
            delete,
            undo,
            brightnessContrast,
            None,
            zoom,
            fitWidth,
        )

        self.statusBar().showMessage(str(self.tr("%s started.")) % __appname__)
        self.statusBar().show()

        if output_file is not None and self._config["auto_save"]:
            logger.warn(
                "If `auto_save` argument is True, `output_file` argument "
                "is ignored and output filename is automatically "
                "set as IMAGE_BASENAME.json."
            )
        self.output_file = output_file
        self.output_dir = output_dir

        # Application state.
        #一些app的初始状态
        self.image = QtGui.QImage()
        self.imageDepth = QtGui.QImage()
        self.imagePath = None
        self.recentFiles = []
        self.maxRecent = 7
        self.otherData = None
        self.zoom_level = 100
        self.fit_window = False
        self.zoom_values = {}  # key=filename, value=(zoom_mode, zoom_value)
        self.brightnessContrast_values = {}
        self.scroll_values = {
            Qt.Horizontal: {},
            Qt.Vertical: {},
        }  # key=filename, value=scroll_value

        if filename is not None and osp.isdir(filename):
            self.importDirImages(filename, load=False)
        else:
            self.filename = filename

        if config["file_search"]:
            self.fileSearch.setText(config["file_search"])
            self.fileSearchChanged()

        # XXX: Could be completely declarative.
        # Restore application settings.
        self.settings = QtCore.QSettings("labelme", "labelme")
        self.recentFiles = self.settings.value("recentFiles", []) or []
        size = self.settings.value("window/size", QtCore.QSize(600, 500))
        position = self.settings.value("window/position", QtCore.QPoint(0, 0))
        state = self.settings.value("window/state", QtCore.QByteArray())
        self.resize(size)
        self.move(position)
        # or simply:
        # self.restoreGeometry(settings['window/geometry']
        self.restoreState(state)

        # Populate the File menu dynamically.
        self.updateFileMenu()
        # Since loading the file may take some time,
        # make sure it runs in the background.
        if self.filename is not None:
            self.queueEvent(functools.partial(self.loadFile, self.filename))

        # Callbacks:
        self.zoomWidget.valueChanged.connect(self.paintCanvas)

        self.populateModeActions()

        # self.firstStart = True
        # if self.firstStart:
        #    QWhatsThis.enterWhatsThisMode()

    def menu(self, title, actions=None):
        menu = self.menuBar().addMenu(title)
        if actions:
            utils.addActions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName("%sToolBar" % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            utils.addActions(toolbar, actions)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        return toolbar

    # Support Functions

    def noShapes(self):
        return not len(self.labelListColor) and len(self.labelListDepth)

#TODO 修改窗口focus，和undo有关
    def focusChangedColor(self):
        self.nowFocus='RGB'


    def focusChangedDepth(self):
        self.nowFocus='Depth'

    #填充模式操作，populate，填充
    def populateModeActions(self):
        tool, menu = self.actions.tool, self.actions.menu
        self.tools.clear()
        utils.addActions(self.tools, tool)
        self.canvasLeft.menus[0].clear()
        utils.addActions(self.canvasLeft.menus[0], menu)
        self.menus.edit.clear()
        actions = (
            self.actions.createMode,
            self.actions.createRectangleMode,
            self.actions.createCircleMode,
            self.actions.createLineMode,
            self.actions.createPointMode,
            self.actions.createLineStripMode,
            self.actions.editMode,
        )
        utils.addActions(self.menus.edit, actions + self.actions.editMenu)


    #dirty和clean应该是两种不同的保存模式

    def setDirty(self):
        # Even if we autosave the file, we keep the ability to undo
        self.actions.undo.setEnabled(self.canvasLeft.isShapeRestorable or self.canvasRight.isShapeRestorable)
        if self._config["auto_save"] or self.actions.saveAuto.isChecked():
            label_file = osp.splitext(self.imagePath)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = osp.join(self.output_dir, label_file_without_path)
            self.saveLabels(label_file,self.saveMode)
            return
        self.dirty = True
        self.actions.save.setEnabled(True)
        title = __appname__
        if self.filename is not None:
            title = "{} - {}*".format(title, self.filename)
        self.setWindowTitle(title)

    def setClean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.createMode.setEnabled(True)
        self.actions.createRectangleMode.setEnabled(True)
        self.actions.createCircleMode.setEnabled(True)
        self.actions.createLineMode.setEnabled(True)
        self.actions.createPointMode.setEnabled(True)
        self.actions.createLineStripMode.setEnabled(True)
        title = __appname__
        if self.filename is not None:
            title = "{} - {}".format(title, self.filename)
        self.setWindowTitle(title)

        if self.hasLabelFile():
            self.actions.deleteFile.setEnabled(True)
        else:
            self.actions.deleteFile.setEnabled(False)


    #正如其注释所言，打开关闭文件之后会改变的action状态，有的会无法选取
    def toggleActions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def queueEvent(self, function):
        QtCore.QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    #resetState应该是重置一下变量，回归初始值
    def resetState(self):
        self.labelListColor.clear()
        self.labelListDepth.clear()
        self.filename = None
        self.imagePath = None
        self.imageData = None
        self.labelFile = None
        self.otherData = None
        self.canvasLeft.resetState()
        self.canvasRight.resetState()

    #labellist是Qt组件，
    def currentItemColor(self):
        items = self.labelListColor.selectedItems()
        if items:
            return items[0]
        return None

    def currentItemDepth(self):
        items = self.labelListDepth.selectedItems()
        if items:
            return items[0]
        return None

    def addRecentFile(self, filename):
        if filename in self.recentFiles:
            self.recentFiles.remove(filename)
        elif len(self.recentFiles) >= self.maxRecent:
            self.recentFiles.pop()
        self.recentFiles.insert(0, filename)

    # Callbacks
    #unDo,函数如其名
    def undoShapeEdit(self):

        if self.nowFocus=='RGB':
            if self.canvasLeft.isShapeRestorable:
                self.canvasLeft.restoreShape()
                self.labelListColor.clear()
                self.labelListDepth.clear()
                self.loadShapes(self.canvasLeft.shapes, self.canvasRight.shapes)
                self.canvasRight.shapesBackups.pop()

            elif self.canvasRight.isShapeRestorable:
                self.canvasRight.restoreShape()
                self.labelListColor.clear()
                self.labelListDepth.clear()
                self.loadShapes(self.canvasLeft.shapes, self.canvasRight.shapes)
                self.canvasLeft.shapesBackups.pop()
        else:
            if self.canvasRight.isShapeRestorable:
                self.canvasRight.restoreShape()
                self.labelListColor.clear()
                self.labelListDepth.clear()
                self.loadShapes(self.canvasLeft.shapes, self.canvasRight.shapes)
                self.canvasLeft.shapesBackups.pop()

            elif self.canvasLeft.isShapeRestorable:
                self.canvasLeft.restoreShape()
                self.labelListColor.clear()
                self.labelListDepth.clear()
                self.loadShapes(self.canvasLeft.shapes, self.canvasRight.shapes)
                self.canvasRight.shapesBackups.pop()


        #FIXME 做出真正意义上的loadshapes

        self.actions.undo.setEnabled(self.canvasLeft.isShapeRestorable or self.canvasRight.isShapeRestorable)


    def tutorial(self):
        url = "https://github.com/wkentaro/labelme/tree/main/examples/tutorial"  # NOQA
        webbrowser.open(url)

    def toggleDrawingSensitive(self, drawing=True):
        """Toggle drawing sensitive.

        In the middle of drawing, toggling between modes should be disabled.
        """
        self.actions.editMode.setEnabled(not drawing)
        self.actions.undoLastPoint.setEnabled(drawing)
        self.actions.undo.setEnabled(not drawing)
        self.actions.delete.setEnabled(not drawing)

    #这部分对应的是，右键选择创建多边形模式之后，就把现有的模式在右键菜单改变为不可选
    def toggleDrawMode(self, edit=True, createMode="point"):
        self.canvasLeft.setEditing(edit)
        self.canvasLeft.createMode = createMode
        self.canvasRight.setEditing(edit)
        self.canvasRight.createMode = createMode
        if edit:
            self.actions.createMode.setEnabled(True)
            self.actions.createRectangleMode.setEnabled(True)
            self.actions.createCircleMode.setEnabled(True)
            self.actions.createLineMode.setEnabled(True)
            self.actions.createPointMode.setEnabled(True)
            self.actions.createLineStripMode.setEnabled(True)
        else:
            if createMode == "polygon":
                self.actions.createMode.setEnabled(False)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "rectangle":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(False)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "line":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(False)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "point":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(False)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "circle":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(False)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(True)
            elif createMode == "linestrip":
                self.actions.createMode.setEnabled(True)
                self.actions.createRectangleMode.setEnabled(True)
                self.actions.createCircleMode.setEnabled(True)
                self.actions.createLineMode.setEnabled(True)
                self.actions.createPointMode.setEnabled(True)
                self.actions.createLineStripMode.setEnabled(False)
            else:
                raise ValueError("Unsupported createMode: %s" % createMode)
        self.actions.editMode.setEnabled(not edit)

    #打开编辑模式，对应上边函数的编辑分支
    def setEditMode(self):
        self.toggleDrawMode(True)

    # 和file menu里open recent有关
    def updateFileMenu(self):
        current = self.filename

        def exists(filename):
            return osp.exists(str(filename))

        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recentFiles if f != current and exists(f)]
        for i, f in enumerate(files):
            icon = utils.newIcon("labels")
            action = QtWidgets.QAction(
                icon, "&%d %s" % (i + 1, QtCore.QFileInfo(f).fileName()), self
            )
            action.triggered.connect(functools.partial(self.loadRecent, f))
            menu.addAction(action)

    #
    def popLabelListColorMenu(self, point):
        self.menus.labelList.exec_(self.labelListColor.mapToGlobal(point))

    def popLabelListDepthMenu(self, point):
        self.menus.labelList.exec_(self.labelListDepth.mapToGlobal(point))

    def duplicateLabel(self, label,mode):
        if mode=='R':
            for i in range(len(self.labelListColor)):
                label_i = self.labelListColor[i].data(Qt.UserRole).label
                if label_i == label:
                    return True
            return False
        if mode=='D':
            for i in range(len(self.labelListDepth)):
                label_i = self.labelListDepth[i].data(Qt.UserRole).label
                if label_i == label:
                    return True
            return False

    def validateLabel(self, label):
        # no validation
        if self._config["validate_label"] is None:
            return True

        for i in range(self.uniqLabelList.count()):
            label_i = self.uniqLabelList.item(i).data(Qt.UserRole)
            if self._config["validate_label"] in ["exact"]:
                if label_i == label:
                    return True
        return False

    #这个是创建完图形之后出现的填写label窗口，编辑label
    def editLabel(self, item=None):
        if item and not isinstance(item, LabelListWidgetItem):
            raise TypeError("item must be LabelListWidgetItem type")

        if not self.canvasLeft.editing() or self.canvasRight.editing():
            return
        if not item:
            item = self.currentItem()
        if item is None:
            return
        shape = item.shape()
        if shape is None:
            return
        # 这个是创建完图形之后出现的填写label窗口
        text, flags, group_id = self.labelDialog.popUp(
            text=shape.label,
            flags=shape.flags,
            group_id=shape.group_id,
        )
        if text is None:
            return
        if not self.validateLabel(text):
            self.errorMessage(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            return
        shape.label = text
        shape.flags = flags
        shape.group_id = group_id

        self._update_shape_color(shape)
        if shape.group_id is None:
            item.setText(
                '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                    html.escape(shape.label), *shape.fill_color.getRgb()[:3]
                )
            )
        else:
            item.setText("{} ({})".format(shape.label, shape.group_id))
        self.setDirty()
        if not self.uniqLabelList.findItemsByLabel(shape.label):
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.UserRole, shape.label)
            self.uniqLabelList.addItem(item)

    #TODO copyallshapes的函数
    def copyAllShapes(self,pressed):

        self.labelFile.shapesDepth=self.labelFile.shapesRGB.copy()
        self.canvasRight.shapes=self.canvasLeft.shapes.copy()
        #FIXME 此时虽然reload，但不能更新label，或者更新也得初始化label再读取，不然就会重复
        #FIXME 此时虽然reload，但不能更新label，或者更新也得初始化label再读取，不然就会重复
        self.labelListColor.clear()
        self.labelListDepth.clear()
        self.loadShapes(self.canvasLeft.shapes,self.canvasRight.shapes)
            # self.canvasRight.update()
            # self.canvasRight.repaint()
    #搜索文件相关，在文件listdock里
    def fileSearchChanged(self):
        self.importDirImages(
            self.lastOpenDir,
            pattern=self.fileSearch.text(),
            load=False,
        )

    #和file在filelist dock里被选取有关
    def fileSelectionChanged(self):
        items = self.fileListWidget.selectedItems()
        if not items:
            return
        item = items[0]

        if not self.mayContinue():
            return
        currIndex = self.imageList.index(str(item.text()))   # self.lastOpenDir
        if currIndex < len(self.imageList):
            filename = self.imageList[currIndex]

            if filename:
                fileNameDepth = filename[:filename.index('color')] + 'depth.png'
                fileNameFull = osp.join(self.lastOpenDir, filename)
                fileDepthFull = osp.join(self.lastOpenDir, fileNameDepth)
                if not osp.exists(fileNameFull):
                    fileNameFull = None
                if not osp.exists(fileDepthFull):
                    fileDepthFull = None
                self.loadFileSelect(fileNameFull, fileDepthFull)

    # React to canvasLeft signals.
    #一旦选择到shape就会调用此函数，用于更改shape是否被选中的状态
    #FIXME Canvas判斷1
    def shapeSelectionChangedColor(self, selected_shapes):
        self.nowFocus='RGB'
        self._noSelectionSlot = True
        self.canvasRight.deSelectShape()
        for shape in self.canvasLeft.selectedShapes:
            shape.selected = False
        self.labelListColor.clearSelection()
        self.canvasLeft.selectedShapes = selected_shapes
        for shape in self.canvasLeft.selectedShapes:
            shape.selected = True
            item = self.labelListColor.findItemByShape(shape)
            self.labelListColor.selectItem(item)
            self.labelListColor.scrollToItem(item)
        self._noSelectionSlot = False
        n_selected = len(selected_shapes)
        self.actions.delete.setEnabled(n_selected)
        self.actions.duplicate.setEnabled(n_selected)
        self.actions.sync.setEnabled(n_selected)
        self.actions.copy.setEnabled(n_selected)
        self.actions.edit.setEnabled(n_selected == 1)

    def shapeSelectionChangedDepth(self, selected_shapes):
        self.nowFocus = 'Depth'
        self._noSelectionSlot = True
        self.canvasLeft.deSelectShape()
        for shape in self.canvasRight.selectedShapes:
            shape.selected = False
        self.labelListDepth.clearSelection()
        self.canvasRight.selectedShapes = selected_shapes
        for shape in self.canvasRight.selectedShapes:
            shape.selected = True
            item = self.labelListDepth.findItemByShape(shape)
            self.labelListDepth.selectItem(item)
            self.labelListDepth.scrollToItem(item)
        self._noSelectionSlot = False
        n_selected = len(selected_shapes)
        self.actions.delete.setEnabled(n_selected)
        self.actions.duplicate.setEnabled(n_selected)
        self.actions.sync.setEnabled(n_selected)
        self.actions.copy.setEnabled(n_selected)
        self.actions.edit.setEnabled(n_selected == 1)

    # 增加label的函数，输入值是一个shape，是新画好的shape
    # FIXME Canvas判斷1
    def addLabelColor(self, shape):
        if shape.group_id is None:
            text = shape.label
        else:
            text = "{} ({})".format(shape.label, shape.group_id)
        label_list_item = LabelListWidgetItem(text, shape)
        self.labelListColor.addItem(label_list_item)
        if not self.uniqLabelList.findItemsByLabel(shape.label):
            item = self.uniqLabelList.createItemFromLabel(shape.label)
            self.uniqLabelList.addItem(item)
            rgb = self._get_rgb_by_label(shape.label)
            self.uniqLabelList.setItemLabel(item, shape.label, rgb)
        self.labelDialog.addLabelHistory(shape.label)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)
        self._update_shape_color(shape)
        label_list_item.setText(
            '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                html.escape(text), *shape.fill_color.getRgb()[:3]
            )
        )
    def addLabelDepth(self, shape):
        if shape.group_id is None:
            text = shape.label
        else:
            text = "{} ({})".format(shape.label, shape.group_id)
        label_list_item = LabelListWidgetItem(text, shape)
        self.labelListDepth.addItem(label_list_item)
        if not self.uniqLabelList.findItemsByLabel(shape.label):
            item = self.uniqLabelList.createItemFromLabel(shape.label)
            self.uniqLabelList.addItem(item)
            rgb = self._get_rgb_by_label(shape.label)
            self.uniqLabelList.setItemLabel(item, shape.label, rgb)
        self.labelDialog.addLabelHistory(shape.label)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)
        #给canvas上的点赋予颜色
        self._update_shape_color(shape)
        label_list_item.setText(
            '{} <font color="#{:02x}{:02x}{:02x}">●</font>'.format(
                html.escape(text), *shape.fill_color.getRgb()[:3]
            )
        )

    #更新颜色，通过get rgb by label函数得到rgb，然后赋值到shape数据结构里
    def _update_shape_color(self, shape):
        r, g, b = self._get_rgb_by_label(shape.label)
        shape.line_color = QtGui.QColor(r, g, b)
        shape.vertex_fill_color = QtGui.QColor(r, g, b)
        shape.hvertex_fill_color = QtGui.QColor(255, 255, 255)
        shape.fill_color = QtGui.QColor(r, g, b, 128)
        shape.select_line_color = QtGui.QColor(255, 255, 255)
        shape.select_fill_color = QtGui.QColor(r, g, b, 155)


    def _get_rgb_by_label(self, label):
        if self._config["shape_color"] == "auto":
            item = self.uniqLabelList.findItemsByLabel(label)[0]
            label_id = self.uniqLabelList.indexFromItem(item).row() + 1
            label_id += self._config["shift_auto_shape_color"]
            return LABEL_COLORMAP[label_id % len(LABEL_COLORMAP)]
        elif (
            self._config["shape_color"] == "manual"
            and self._config["label_colors"]
            and label in self._config["label_colors"]
        ):
            return self._config["label_colors"][label]
        elif self._config["default_shape_color"]:
            return self._config["default_shape_color"]
        return (0, 255, 0)

    #删除label，在删除shape时候调用
    # FIXME Canvas判斷3
    def remLabels(self, shapes):
        if self.nowFocus=='RGB':
            for shape in shapes:
                item = self.labelListColor.findItemByShape(shape)
                self.labelListColor.removeItem(item)
        else:
            for shape in shapes:
                item = self.labelListDepth.findItemByShape(shape)
                self.labelListDepth.removeItem(item)

    #读取shape
    # TODO 两边显示点管线：读取形状，如果此函数加入了canvasright，就是同时显示两边，那符合需求吗，试一试
    # FIXME Canvas判斷4
    def loadShapeSync(self, shapestoR, shapestoD, replace=True):
        self._noSelectionSlot = True
        labelShapeColor = []
        labelShapeDepth = []
        dupR = []
        dupD = []
        dupROri = []
        dupDOri = []
        for it in self.labelListColor:
            labelShapeColor.append(it.shape())
        for it in self.labelListDepth:
            labelShapeDepth.append(it.shape())
        for it in shapestoR:
            for it2 in labelShapeColor:
                if it.label == it2.label:
                    dupD.append(it)
                    dupDOri.append(it2)

        for it in shapestoD:
            for it2 in labelShapeDepth:
                if it.label == it2.label:
                    dupR.append(it)
                    dupROri.append(it2)

        if len(dupD)!=0:
            reply = QtWidgets.QMessageBox.question(self, 'Message', 'Points {} have been exist in RGB canvas. Do you want to overwrite them?'.format([it.label for it in dupD]),
                                                   QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                   QtWidgets.QMessageBox.No)

            if reply == QtWidgets.QMessageBox.No:
                for it in dupD:
                    for it2 in shapestoR:
                        if it2.label == it.label:
                            shapestoR.remove(it2)
                # label shape里去除现在说重复的shape，然后加上整个shapeto，
                labelShapeColor = labelShapeColor + shapestoR
            else:
                for it2 in dupDOri:
                    for it in labelShapeColor:
                        if it.label == it2.label:
                            item = self.labelListColor.findItemByShape(it)
                            self.labelListColor.removeItem(item)
                            labelShapeColor.remove(it)
                            if len(labelShapeColor) == 0:
                                break
                    if len(labelShapeColor)==0:
                        break
                labelShapeColor = labelShapeColor + shapestoR

        elif len(dupR)!=0:
            reply = QtWidgets.QMessageBox.question(self, 'Message', 'Points {} have been exist in Depth canvas. Do you want to overwrite them?'.format([it.label for it in dupR]),
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                QtWidgets.QMessageBox.No)

            if reply == QtWidgets.QMessageBox.No:
                for it in dupR:
                    for it2 in shapestoD:
                        if it2.label == it.label:
                            shapestoD.remove(it2)

                #label shape里去除现在说重复的shape，然后加上整个shapeto，
                labelShapeDepth = labelShapeDepth + shapestoD
            else:
                for it2 in dupROri:
                    for it in labelShapeDepth:
                        if it.label==it2.label:
                            item = self.labelListDepth.findItemByShape(it)
                            self.labelListDepth.removeItem(item)
                            labelShapeDepth.remove(it)
                            if len(labelShapeColor) == 0:
                                break
                    if len(labelShapeDepth)==0:
                        break
                labelShapeDepth=labelShapeDepth+shapestoD
        else:
            labelShapeDepth = labelShapeDepth + shapestoD
            labelShapeColor = labelShapeColor + shapestoR
        if len(shapestoR) != 0:
            for shape in shapestoR:
                self.addLabelColor(shape)
            self.labelListColor.clearSelection()
            self.canvasLeft.loadShapes(labelShapeColor, replace=replace)
            self.canvasLeft.selectShapes(labelShapeColor)
            self.canvasLeft.deSelectShape()
            for it in shapestoR:
                itm=self.labelListColor.findItemByShape(it)
                self.labelListColor.selectItem(itm)
            self.nowFocus = 'RGB'



        if len(shapestoD) != 0:
            for shape in shapestoD:
                self.addLabelDepth(shape)
            self.labelListDepth.clearSelection()
            self.canvasRight.loadShapes(labelShapeDepth, replace=replace)
            self.canvasRight.selectShapes(labelShapeDepth)
            self.canvasRight.deSelectShape()
            for it in shapestoD:
                itm=self.labelListDepth.findItemByShape(it)
                self.labelListDepth.selectItem(itm)
            self.nowFocus = 'Depth'



        self._noSelectionSlot = False

    def loadShapes(self, shapesR, shapesD, replace=True):
        self._noSelectionSlot = True


        if len(shapesR)!=0:
            for shape in shapesR:

                self.addLabelColor(shape)
            self.labelListColor.clearSelection()
            self.canvasLeft.loadShapes(shapesR, replace=replace)
        if len(shapesD)!=0:
            for shape in shapesD:
                self.addLabelDepth(shape)
            self.labelListDepth.clearSelection()
            self.canvasRight.loadShapes(shapesD, replace=replace)

        self._noSelectionSlot = False
    #读取labels


    #TODO 两边显示点管线：读取labels，是两边同样显示的关键
    def loadLabels(self, shapesrgb,shapesdepth,side):
        sRGB = []
        sDepth=[]
        if side=='R':
            shapes=shapesrgb
            for shape in shapes:
                label = shape["label"]
                points = shape["points"]
                shape_type = shape["shape_type"]
                flags = shape["flags"]
                group_id = shape["group_id"]
                other_data = shape["other_data"]

                if not points:
                    # skip point-empty shape
                    continue

                shape = Shape(
                    label=label,
                    shape_type=shape_type,
                    group_id=group_id,
                )
                for x, y in points:
                    shape.addPoint(QtCore.QPointF(x, y))
                shape.close()

                default_flags = {}
                if self._config["label_flags"]:
                    for pattern, keys in self._config["label_flags"].items():
                        if re.match(pattern, label):
                            for key in keys:
                                default_flags[key] = False
                shape.flags = default_flags
                shape.flags.update(flags)
                shape.other_data = other_data

                sRGB.append(shape)
        elif side=='D':
            shapes=shapesdepth
            for shape in shapes:
                label = shape["label"]
                points = shape["points"]
                shape_type = shape["shape_type"]
                flags = shape["flags"]
                group_id = shape["group_id"]
                other_data = shape["other_data"]

                if not points:
                    # skip point-empty shape
                    continue

                shape = Shape(
                    label=label,
                    shape_type=shape_type,
                    group_id=group_id,
                )
                for x, y in points:
                    shape.addPoint(QtCore.QPointF(x, y))
                shape.close()

                default_flags = {}
                if self._config["label_flags"]:
                    for pattern, keys in self._config["label_flags"].items():
                        if re.match(pattern, label):
                            for key in keys:
                                default_flags[key] = False
                shape.flags = default_flags
                shape.flags.update(flags)
                shape.other_data = other_data

                sDepth.append(shape)
        else:
            for shape in shapesrgb:
                label = shape["label"]
                points = shape["points"]
                shape_type = shape["shape_type"]
                flags = shape["flags"]
                group_id = shape["group_id"]
                other_data = shape["other_data"]

                if not points:
                    # skip point-empty shape
                    continue

                shape = Shape(
                    label=label,
                    shape_type=shape_type,
                    group_id=group_id,
                )
                for x, y in points:
                    shape.addPoint(QtCore.QPointF(x, y))
                shape.close()

                default_flags = {}
                if self._config["label_flags"]:
                    for pattern, keys in self._config["label_flags"].items():
                        if re.match(pattern, label):
                            for key in keys:
                                default_flags[key] = False
                shape.flags = default_flags
                shape.flags.update(flags)
                shape.other_data = other_data

                sRGB.append(shape)

            for shape in shapesdepth:
                label = shape["label"]
                points = shape["points"]
                shape_type = shape["shape_type"]
                flags = shape["flags"]
                group_id = shape["group_id"]
                other_data = shape["other_data"]

                if not points:
                    # skip point-empty shape
                    continue

                shape = Shape(
                    label=label,
                    shape_type=shape_type,
                    group_id=group_id,
                )
                for x, y in points:
                    shape.addPoint(QtCore.QPointF(x, y))
                shape.close()

                default_flags = {}
                if self._config["label_flags"]:
                    for pattern, keys in self._config["label_flags"].items():
                        if re.match(pattern, label):
                            for key in keys:
                                default_flags[key] = False
                shape.flags = default_flags
                shape.flags.update(flags)
                shape.other_data = other_data

                sDepth.append(shape)
        self.loadShapes(sRGB,sDepth)

    #读取flag
    def loadFlags(self, flags):
        self.flag_widget.clear()
        for key, flag in flags.items():
            item = QtWidgets.QListWidgetItem(key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if flag else Qt.Unchecked)
            self.flag_widget.addItem(item)

    #保存label
    def saveLabels(self, filename,savemode):
        lf = LabelFile()

        def format_shape(s):
            data = s.other_data.copy()
            data.update(
                dict(
                    label=s.label.encode("utf-8") if PY2 else s.label,
                    points=[(p.x(), p.y()) for p in s.points],
                    group_id=s.group_id,
                    shape_type=s.shape_type,
                    flags=s.flags,
                )
            )
            return data
        #TODO 在此写入固定的dict内容，包括所有的部位label
        #我想的是，shapes的结构先不变，按照梁佳敏的存，然后在shapes里找，看看label里哪些有变化，就替换，这样保证shapes结构不变
        oridict={
            "label":"",
            "points":None,
            "group_id":None,
            "shape_type":"point",
            "flags":{}
        }
        shape_dictR,shape_dictD=[],[]

        # for it in self._config["labels"]:
        #     dictit=oridict.copy()
        #     dictit['label']=it
        #     shape_dictR.append(dictit)
        #     shape_dictD.append(dictit)

        shapesColor = [format_shape(item.shape()) for item in self.labelListColor]
        shapesDepth = [format_shape(item.shape()) for item in self.labelListDepth]
        with open(filename, 'r', encoding='utf8') as fp:
            json_data = json.load(fp)
        shape_dictR=json_data['shapes_rgb']
        shape_dictD = json_data['shapes_depth']
        if len(shapesColor)>26 or len(shapesDepth)>26:
            self.errorMessage(
                self.tr("Error saving label data,Label more than 26."),self.tr("Repeat shape:{}")
            )

        #TODO ！！！！！保存函数！！！！！把标的shapes替换到对应dict位置
        for its in shapesColor:
            find=its['label']
            for i in range(0,len(shape_dictR)):
                if shape_dictR[i]['label']==find:
                    shape_dictR[i]=its
        for its in shapesDepth:
            find=its['label']
            for i in range(0,len(shape_dictD)):
                if shape_dictD[i]['label']==find:
                    shape_dictD[i]=its
        if savemode=='R':
            shape_dictR=shape_dictR
            shape_dictD=shape_dictD
        elif savemode=='D':
            shape_dictR=shape_dictR
            shape_dictD=shape_dictD
        else:
            shape_dictR = shape_dictR
            shape_dictD = shape_dictD



        flags = {}
        for i in range(self.flag_widget.count()):
            item = self.flag_widget.item(i)
            key = item.text()
            flag = item.checkState() == Qt.Checked
            flags[key] = flag
        try:
            imagePath = osp.relpath(self.imagePath, osp.dirname(filename))
            imageData = self.imageData if self._config["store_data"] else None
            if osp.dirname(filename) and not osp.exists(osp.dirname(filename)):
                os.makedirs(osp.dirname(filename))
            lf.save(
                filename=filename,
                shapes_rgb=shape_dictR,
                shapes_depth=shape_dictD,
                imagePath=imagePath,
            imageHeight = self.image.height(),
            imageWidth = self.image.width(),
                imageData=imageData,
                otherData=self.otherData,
                flags=flags,
            )

            self.labelFile = lf
            items = self.fileListWidget.findItems(
                self.imagePath, Qt.MatchExactly
            )
            if len(items) > 0:
                if len(items) != 1:
                    raise RuntimeError("There are duplicate files.")
                items[0].setCheckState(Qt.Checked)
            # disable allows next and previous image to proceed
            # self.filename = filename
            return True
        except LabelFileError as e:
            self.errorMessage(
                self.tr("Error saving label data"), self.tr("<b>%s</b>") % e
            )
            return False
    #堆叠选择shape，暂时未知用途 duplicate 复制
    def duplicateSelectedShape(self):
        added_shapesL = self.canvasLeft.duplicateSelectedShapes()
        added_shapesR = self.canvasRight.duplicateSelectedShapes()
        self.labelListColor.clearSelection()
        self.labelListDepth.clearSelection()
        for shape in added_shapesL:
            self.addLabelColor(shape)
        for shape in added_shapesR:
            self.addLabelDepth(shape)
        self.setDirty()


    #TODO Sink points
    # self.labelFile.shapesDepth = self.labelFile.shapesRGB.copy()
    # self.canvasRight.shapes = self.canvasLeft.shapes.copy()
    # # FIXME 此时虽然reload，但不能更新label，或者更新也得初始化label再读取，不然就会重复
    # # FIXME 此时虽然reload，但不能更新label，或者更新也得初始化label再读取，不然就会重复
    # self.labelListColor.clear()
    # self.labelListDepth.clear()
    # self.loadShapes(self.canvasLeft.shapes, self.canvasRight.shapes)

    def pasteSelectedShape(self):
        self.loadShapes(self._copied_shapes,self._copied_shapes, replace=False)
        self.setDirty()

    #paste
    def copySelectedShape(self):
        self._copied_shapes = [s.copy() for s in self.canvasLeft.selectedShapes]
        self.actions.paste.setEnabled(len(self._copied_shapes) > 0)

    def transferSelectedShape(self):
        added_shapesL = [s.copy() for s in self.canvasLeft.selectedShapes]
        added_shapesR = [s.copy() for s in self.canvasRight.selectedShapes]
        self.loadShapeSync(added_shapesR,added_shapesL, replace=True)
        self.setDirty()

        self.toggleDrawMode(True)
        # for shape in added_shapesL:
        #     self.addLabelDepth(shape)
        # for shape in added_shapesR:
        #     self.addLabelColor(shape)
        # self.setDirty()

    #copy，但dirty啥意思？
    def pasteSelectedShape(self):
        self.loadShapes(self._copied_shapes,self._copied_shapes, replace=False)
        self.setDirty()

    #paste
    def copySelectedShape(self):
        self._copied_shapes = [s.copy() for s in self.canvasLeft.selectedShapes]
        self.actions.paste.setEnabled(len(self._copied_shapes) > 0)

    #从labellist里选择label，选择之后会同时选中canvas上的shape
    def labelSelectionChanged(self):
        if self._noSelectionSlot:
            return
        if self.canvasLeft.editing():
            self.labelListDepth.clearSelection()
            selected_shapesColor = []
            for item in self.labelListColor.selectedItems():
                selected_shapesColor.append(item.shape())
            if selected_shapesColor:
                self.canvasLeft.selectShapes(selected_shapesColor)
            else:
                self.canvasLeft.deSelectShape()
        else:
            self.labelListColor.clearSelection()
            selected_shapesDepth = []
            for item in self.labelListDepth.selectedItems():
                selected_shapesDepth.append(item.shape())
            if selected_shapesDepth:
                self.canvasRight.selectShapes(selected_shapesDepth)
            else:
                self.canvasRight.deSelectShape()

    def labelSelectionChangedRGB(self):
        if self._noSelectionSlot:
            return
        self.canvasRight.setEditing(False)
        if self.canvasLeft.editing():
            self.labelListDepth.clearSelection()
            selected_shapesColor = []
            for item in self.labelListColor.selectedItems():
                selected_shapesColor.append(item.shape())
            if selected_shapesColor:
                self.canvasLeft.selectShapes(selected_shapesColor)
                self.canvasRight.deSelectShape()
            else:
                self.canvasLeft.deSelectShape()
        self.canvasRight.setEditing(True)

    def labelSelectionChangedDepth(self):
        if self._noSelectionSlot:
            return
        self.canvasLeft.setEditing(False)
        if self.canvasRight.editing():
            self.labelListColor.clearSelection()
            selected_shapesDepth = []
            for item in self.labelListDepth.selectedItems():
                selected_shapesDepth.append(item.shape())
            if selected_shapesDepth:
                self.canvasRight.selectShapes(selected_shapesDepth)
                self.canvasLeft.deSelectShape()
            else:
                self.canvasRight.deSelectShape()
        self.canvasLeft.setEditing(True)

    #itemchange，都是和label dock操作相关的内容
    def labelItemChangedRGB(self, item):
        shape = item.shape()
        self.canvasLeft.setShapeVisible(shape, item.checkState() == Qt.Checked)
        numberColor = len(self.labelListColor)
        self.shape_dockColor.setWindowTitle("RGB Polygon Labels ({})".format(numberColor))   

    #labelOrderChanged
    def labelOrderChangedRGB(self):
        self.setDirty()
        #TODO LabelList要分开
        self.canvasLeft.loadShapes([item.shape() for item in self.labelListColor])


    def labelItemChangedDepth(self, item):
        shape = item.shape()
        self.canvasRight.setShapeVisible(shape, item.checkState() == Qt.Checked)

        numberDepth = len(self.labelListDepth)
        self.shape_dockDepth.setWindowTitle("Depth Polygon Labels ({})".format(numberDepth)) 

    #labelOrderChanged
    def labelOrderChangedDepth(self):
        self.setDirty()
        #TODO LabelList要分开
        self.canvasRight.loadShapes([item.shape() for item in self.labelListDepth])
    # Callback functions:回调函数

    def itemChangedUniqLabelList(self):
        number = len(self.uniqLabelList)
        self.label_dock.setWindowTitle("Label Lists ({})".format(number))   

    #新建shape，新建任何shape的时候都会调用此函数
    def newShapeDepth(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        self.nowFocus = 'Depth'
        items = self.uniqLabelList.selectedItems()
        text = None
        if items:
            text = items[0].data(Qt.UserRole)
        flags = {}
        group_id = None
        if self._config["display_label_popup"] or not text:
            previous_text = self.labelDialog.edit.text() #弹出对话框，用来输入label信息
            text, flags, group_id = self.labelDialog.popUp(text)
            if not text:
                self.labelDialog.edit.setText(previous_text)

        if text and not self.validateLabel(text):
            self.errorMessage(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            text = ""
        if text and self.duplicateLabel(text,'D'):
            self.errorMessage(
                self.tr("Repeated label"),
                self.tr("Repeated label '{}', not allowed to create.").format(
                    text
                ),
            )
            for it in self.labelListDepth:
                aa=it.shape()
                if aa.label==text:
                    dupshape=it.shape()
                    break
            text = ""
            self.toggleDrawMode(True)
            itemdup = self.labelListDepth.findItemByShape(dupshape)
            self.labelListDepth.selectItem(itemdup)
        if text:
            self.labelListColor.clearSelection()
            self.labelListDepth.clearSelection()
            shape = self.canvasRight.setLastLabel(text, flags)
            shape.group_id = group_id
            self.addLabelDepth(shape)
            self.actions.editMode.setEnabled(True)
            self.actions.undoLastPoint.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.setDirty()
        else:
            self.canvasRight.undoLastLine()
            self.canvasRight.shapesBackups.pop()

    def newShapeRGB(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        self.nowFocus = 'Depth'
        items = self.uniqLabelList.selectedItems()
        text = None
        if items:
            text = items[0].data(Qt.UserRole)
        flags = {}
        group_id = None
        if self._config["display_label_popup"] or not text:
            previous_text = self.labelDialog.edit.text() #弹出对话框，用来输入label信息
            text, flags, group_id = self.labelDialog.popUp(text)
            if not text:
                self.labelDialog.edit.setText(previous_text)

        if text and not self.validateLabel(text):
            self.errorMessage(
                self.tr("Invalid label"),
                self.tr("Invalid label '{}' with validation type '{}'").format(
                    text, self._config["validate_label"]
                ),
            )
            text = ""

        if text and self.duplicateLabel(text,'R'):
            self.errorMessage(
                self.tr("Repeated label"),
                self.tr("Repeated label '{}', not allowed to create.").format(
                    text
                ),
            )
            for it in self.labelListColor:
                aa=it.shape()
                if aa.label==text:
                    dupshape=it.shape()
                    break
            text = ""
            self.toggleDrawMode(True)
            itemdup = self.labelListColor.findItemByShape(dupshape)
            self.labelListColor.selectItem(itemdup)

        if text:
            self.labelListColor.clearSelection()
            self.labelListDepth.clearSelection()
            shape = self.canvasLeft.setLastLabel(text, flags)
            shape.group_id = group_id
            self.addLabelColor(shape)
            self.actions.editMode.setEnabled(True)
            self.actions.undoLastPoint.setEnabled(False)
            self.actions.undo.setEnabled(True)
            self.setDirty()
        else:
            self.canvasLeft.undoLastLine()
            self.canvasLeft.shapesBackups.pop()

    #和画布有关的缩放滚动
    def scrollRequest(self, delta, orientation):
        units = -delta * 0.1  # natural scroll
        bar = self.scrollBars[orientation]
        value = bar.value() + bar.singleStep() * units
        self.setScroll(orientation, value)

    def setScroll(self, orientation, value):
        self.scrollBars[orientation].setValue(value)
        self.scroll_values[orientation][self.filename] = value

    def setZoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.MANUAL_ZOOM
        self.zoomWidget.setValue(value)
        self.zoom_values[self.filename] = (self.zoomMode, value)

    def addZoom(self, increment=1.1):
        zoom_value = self.zoomWidget.value() * increment
        if increment > 1:
            zoom_value = math.ceil(zoom_value)
        else:
            zoom_value = math.floor(zoom_value)
        self.setZoom(zoom_value)

    def zoomRequest(self, delta, pos):
        canvas_width_old = self.canvasLeft.width()
        units = 1.1
        if delta < 0:
            units = 0.9
        self.addZoom(units)

        canvas_width_new = self.canvasLeft.width()
        if canvas_width_old != canvas_width_new:
            canvas_scale_factor = canvas_width_new / canvas_width_old

            x_shift = round(pos.x() * canvas_scale_factor) - pos.x()
            y_shift = round(pos.y() * canvas_scale_factor) - pos.y()

            self.setScroll(
                Qt.Horizontal,
                self.scrollBars[Qt.Horizontal].value() + x_shift,
            )
            self.setScroll(
                Qt.Vertical,
                self.scrollBars[Qt.Vertical].value() + y_shift,
            )
    #对应符合窗口大小按钮
    def setFitWindow(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoomMode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjustScale()
    #对应符合宽度按钮
    def setFitWidth(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjustScale()

    def enableKeepPrevScale(self, enabled):
        self._config["keep_prev_scale"] = enabled
        self.actions.keepPrevScale.setChecked(enabled)

    def onNewBrightnessContrast(self, qimage):
        self.canvasLeft.loadPixmap(
            QtGui.QPixmap.fromImage(qimage), clear_shapes=False
        )

    def brightnessContrast(self, value):
        dialog = BrightnessContrastDialog(
            utils.img_data_to_pil(self.imageData),
            self.onNewBrightnessContrast,
            parent=self,
        )
        brightness, contrast = self.brightnessContrast_values.get(
            self.filename, (None, None)
        )
        if brightness is not None:
            dialog.slider_brightness.setValue(brightness)
        if contrast is not None:
            dialog.slider_contrast.setValue(contrast)
        dialog.exec_()

        brightness = dialog.slider_brightness.value()
        contrast = dialog.slider_contrast.value()
        self.brightnessContrast_values[self.filename] = (brightness, contrast)

    def togglePolygons(self, value):
        for item in self.labelListColor:
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)
        for item in self.labelListDepth:
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)


    def UpdatePInfo(self):
        if self.labelFile==None:
            return
        newPose=self.patientINFO.Pose_combo.currentText()
        newHeight=self.patientINFO.pInfoTextH.toPlainText()
        newWeight=self.patientINFO.pInfoTextW.toPlainText()

        self.otherData["patientHeight"]= newHeight
        self.otherData["patientWeight"] = newWeight
        self.otherData["patientPose"] = newPose
        self.saveFile()

    #创建默认json
    def saveDefaultLabels(self,filename):

        jsontext= {'version': '5.0.1', 'flags': {'__ignore__': True, 'occlusion': False, 'no_occlusion': False},
                   'shapes_rgb': [
                       {'label': 'HEADTOP', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'NECK', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SHOULDER_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SHOULDER_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point',
                        'flags': {}},
                       {'label': 'ELBOW_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'ELBOW_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'WRIST_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'WRIST_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'HIP_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'HIP_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'GROIN', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'KNEE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'KNEE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'ANKLE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'ANKLE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EYE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EYE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EAR_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EAR_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'NOSE', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'BIGTOE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'BIGTOE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SMALLTOE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SMALLTOE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point',
                        'flags': {}},
                       {'label': 'HEEL_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'HEEL_RIGH', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}}],
                   'shapes_depth': [
                       {'label': 'HEADTOP', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'NECK', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SHOULDER_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SHOULDER_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point',
                        'flags': {}},
                       {'label': 'ELBOW_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'ELBOW_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'WRIST_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'WRIST_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'HIP_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'HIP_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'GROIN', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'KNEE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'KNEE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'ANKLE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'ANKLE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EYE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EYE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EAR_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'EAR_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'NOSE', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'BIGTOE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'BIGTOE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SMALLTOE_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'SMALLTOE_RIGHT', 'points': None, 'group_id': None, 'shape_type': 'point',
                        'flags': {}},
                       {'label': 'HEEL_LEFT', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}},
                       {'label': 'HEEL_RIGH', 'points': None, 'group_id': None, 'shape_type': 'point', 'flags': {}}],
                   'imagePath': filename[filename.find('patient'):filename.find('_label')], 'patientHeight': 0, 'patientWeight': 0, 'patientPose': 'HFS',
                   'calibrationExist': True, 'creator': 'default', 'reviewer': None}
        with open(filename, 'w') as f:
            json.dump(jsontext,f,indent=4,ensure_ascii=False)

    #读取文件，这个可能要改动


    def calThresh(self, data):
        flat_data = data.flatten()
        flat_data = np.sort(flat_data)
        flat_data = flat_data[:int(0.97 * flat_data.size)]  # use 97% data to eliminate outliers

        mean = np.mean(flat_data)
        sigma = np.std(flat_data)
        # print(mean + 3*sigma)
        thresh = np.uint16(mean + 3 * sigma)
        return thresh

    # TODO 读取文件
    def loadFileSelect(self, filenameRGB=None, filenameDepth=None):
        """Load the specified file, or the last opened file if None."""

        if len(self.imageList) > 1:  # open dir
            # changing fileListWidget loads file
            if filenameRGB is not None:
                filenameBasename = filenameRGB.replace(self.lastOpenDir + '\\', '')

                if filenameBasename in self.imageList and (
                        self.fileListWidget.currentRow() != self.imageList.index(filenameBasename)
                ):
                    self.fileListWidget.setCurrentRow(self.imageList.index(filenameBasename))
                    self.fileListWidget.repaint()
                    return

            if filenameDepth is not None:
                filenameDepthBasename = filenameDepth.replace(self.lastOpenDir + '\\', '')

                if filenameDepthBasename in self.imageList and (
                        self.fileListWidget.currentRow() != self.imageList.index(filenameDepthBasename)
                ):
                    self.fileListWidget.setCurrentRow(self.imageList.index(filenameDepthBasename))
                    self.fileListWidget.repaint()
                    return

        self.resetState()
        self.canvasLeft.setEnabled(False)
        self.canvasRight.setEnabled(False)

        # if filenameRGB is None:
        #     filenameRGB = self.settings.value("filename", "")
        # filenameRGB = str(filenameRGB)

        # assumes same name, but json extension
        if filenameRGB is not None:
            self.status(
                str(self.tr("Loading %s...")) % osp.basename(str(filenameRGB))
            )

        # if filenameDepth is None:
        #     filenameDepth = self.settings.value("filename", "")

        # assumes same name, but json extension
        if filenameDepth is not None:
            self.status(
                str(self.tr("Loading %s...")) % osp.basename(str(filenameDepth))
            )

        # TODO
        if filenameRGB is not None:
            label_fileColor = osp.splitext(filenameRGB)[0]
            label_fileColor = label_fileColor[:label_fileColor.index('color')] + 'label.json'
        elif filenameDepth is not None:
            label_fileColor = osp.splitext(filenameDepth)[0]
            label_fileColor = label_fileColor[:label_fileColor.index('depth')] + 'label.json'
        label_fileDepth = label_fileColor
        if self.output_dir:
            label_file_without_path_Color = osp.basename(label_fileColor)
            label_fileColor = osp.join(self.output_dir, label_file_without_path_Color)
            label_file_without_path_Depth = osp.basename(label_fileDepth)
            label_fileDepth = osp.join(self.output_dir, label_file_without_path_Depth)
        if QtCore.QFile.exists(label_fileColor) and LabelFile.is_label_file(
                label_fileColor
        ):
            try:
                self.labelFile = LabelFile(label_fileColor)
            except LabelFileError as e:
                # TODO 创建默认Json文件
                self.saveDefaultLabels(label_fileColor)
                self.labelFile = LabelFile(label_fileColor)
            self.imageData = self.labelFile.imageData
            self.imagePath = osp.join(
                osp.dirname(label_fileColor),
                self.labelFile.imagePath,
            )
            self.otherData = self.labelFile.otherData

        else:

            try:
                self.labelFile = LabelFile(label_fileColor)
            except LabelFileError as e:

                # TODO 创建默认Json文件
                self.saveDefaultLabels(label_fileColor)
                self.labelFile = LabelFile(label_fileColor)


        # if os.path.exists(filenameRGB):
        if filenameRGB is not None:

            self.imageData = LabelFile.load_image_file(filenameRGB)
            if self.imageData:
                self.imagePath = filenameRGB
            # self.labelFile = None
            image = QtGui.QImage.fromData(self.imageData)

        # if os.path.exists(filenameDepth):
        if filenameDepth is not None:
            self.imageDataDepthori = cv2.imread(filenameDepth, cv2.IMREAD_ANYDEPTH)
            widthD = self.imageDataDepthori.shape[1]
            heightD = self.imageDataDepthori.shape[0]
            img_rgb_data = self.imageDataDepthori

            thresh = self.calThresh(img_rgb_data)

            img_rgb_data[img_rgb_data > thresh] = thresh
            min_value = np.min(img_rgb_data)
            max_value = np.max(img_rgb_data)

            img_rgb_data = (img_rgb_data - min_value) * 255. / (max_value - min_value)
            img_rgb_data = np.uint8(img_rgb_data)

            img_rgb_data = cv2.applyColorMap(img_rgb_data, colormap=cv2.COLORMAP_BONE)
            # cv2 中的色度图有十几种，其中最常用的是 cv2.COLORMAP_JET，蓝色表示较高的深度值，红色表示较低的深度值。
            # cv.convertScaleAbs() 函数中的 alpha 的大小与深度图中的有效距离有关，如果像我一样默认深度图中的所有深度值都在有效距离内，并已经手动将16位深度转化为了8位深度，则 alpha 可以设为1。
            img_rgb_data = cv2.applyColorMap(cv2.convertScaleAbs(img_rgb_data, alpha=1), cv2.COLORMAP_BONE)
            # image = QtGui.QImage.fromData(self.imageData)
            imageDepth = QtGui.QImage(img_rgb_data.data, widthD, heightD, widthD * 3, QtGui.QImage.Format_RGB888)

        # self.image = image
        # self.imageDepth = imageDepth
        self.filename = filenameRGB
        self.filenameDepth = filenameDepth

        if self._config["keep_prev"]:
            # FIXME 这个明显就上边的没用到
            prev_shapes = self.canvasLeft.shapes

        # current_labelsR=self.labelFile.shapesRGB
        # current_labelsD=self.labelFile.shapesDepth
        # self.canvasLeft._shapes=current_labelsR
        # self.canvasRight._shapes=current_labelsD

        if filenameRGB is not None:
            self.canvasLeft.loadPixmap(QtGui.QPixmap.fromImage(image))
            self.image = image
            self.canvasLeft.setEnabled(True)
            current_labelsR = self.labelFile.shapesRGB
            self.canvasLeft._shapes = current_labelsR
        if filenameDepth is not None:
            self.canvasRight.loadPixmap(QtGui.QPixmap.fromImage(imageDepth))
            self.imageDepth = imageDepth
            self.canvasRight.setEnabled(True)
            current_labelsD = self.labelFile.shapesDepth
            self.canvasRight._shapes = current_labelsD

        flags = {k: False for k in self._config["flags"] or []}
        if self.labelFile:
            # TODO 這裏是讀取label,然后把label中的shapes给赋值，显示到图片中
            self.loadLabels(self.labelFile.shapesRGB, self.labelFile.shapesDepth, 0)
            if self.labelFile.flags is not None:
                flags.update(self.labelFile.flags)
        self.loadFlags(flags)
        if self._config["keep_prev"] and self.noShapes():
            self.loadShapes(prev_shapes, replace=False)
            self.setDirty()
        else:
            self.setClean()
        # self.canvasLeft.setEnabled(True)
        # self.canvasRight.setEnabled(True)
        # set zoom values
        # TODO 這裏修改自適應的zoom
        is_initial_load = not self.zoom_values
        if self.filename in self.zoom_values:
            self.zoomMode = self.zoom_values[self.filename][0]
            self.setZoom(self.zoom_values[self.filename][1])
        elif is_initial_load or not self._config["keep_prev_scale"]:
            self.adjustScale(initial=True)
        # set scroll values

        for orientation in self.scroll_values:
            if self.filename in self.scroll_values[orientation]:
                self.setScroll(
                    orientation, self.scroll_values[orientation][self.filename]
                )

        if filenameRGB is not None:
            # set brightness contrast values
            dialog = BrightnessContrastDialog(
                utils.img_data_to_pil(self.imageData),
                self.onNewBrightnessContrast,
                parent=self,
            )
            brightness, contrast = self.brightnessContrast_values.get(
                self.filename, (None, None)
            )
            if self._config["keep_prev_brightness"] and self.recentFiles:
                brightness, _ = self.brightnessContrast_values.get(
                    self.recentFiles[0], (None, None)
                )
            if self._config["keep_prev_contrast"] and self.recentFiles:
                _, contrast = self.brightnessContrast_values.get(
                    self.recentFiles[0], (None, None)
                )
            if brightness is not None:
                dialog.slider_brightness.setValue(brightness)
            if contrast is not None:
                dialog.slider_contrast.setValue(contrast)
            self.brightnessContrast_values[self.filename] = (brightness, contrast)
            if brightness is not None or contrast is not None:
                dialog.onNewValue(None)

            # TODO 搞清這些函數是幹啥的
            self.paintCanvas()
            self.addRecentFile(self.filename)
            self.toggleActions(True)
            self.canvasLeft.setFocus()
            self.canvasRight.setFocus()
            self.status(str(self.tr("Loaded %s")) % osp.basename(str(filenameRGB)))

        # 更新病人信息到label

        self.patientINFO.LoadInfo(self.labelFile)

        # check the calibration file 
        basename = os.path.basename(self.labelFile.filename)
        calibrationPath = os.path.join(self.labelFile.filename.replace(basename, ""), "calibration.yml")
        flag = os.path.exists(calibrationPath)

        if (flag ^ self.labelFile.otherData["calibrationExist"]):
            # warning box
            if flag:
                firstMess = "is exist"
                secondMess = "is not exist"
            else:
                firstMess = "is not exist"
                secondMess = "is exist"
            reply = QtWidgets.QMessageBox.warning(self, "Tips", "Do you want to change the calibration exist in json file? Currently the calibration file {}, while the calibrationExist flag in .json file {}.".format(firstMess, secondMess), \
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.Yes)
            if reply == QtWidgets.QMessageBox.Yes:
                self.labelFile.otherData["calibrationExist"] = flag
                self.UpdatePInfo()   # auto save
                
        self.patientINFO.Update.clicked.connect(lambda: self.UpdatePInfo())
        return True

    def resizeEvent(self, event):
        if (
            self.canvasLeft
            and not self.image.isNull()
            and self.zoomMode != self.MANUAL_ZOOM
        ):
            self.adjustScale()
        super(MainWindow, self).resizeEvent(event)

    #把图片画到canvas中
    def paintCanvas(self):
        # assert not self.image.isNull(), "cannot paint null image"
        if not self.image.isNull():
            self.canvasLeft.scale = 0.01 * self.zoomWidget.value()
            self.canvasLeft.adjustSize()
            self.canvasLeft.update()
        if not self.imageDepth.isNull():
            self.canvasRight.scale = 0.01 * self.zoomWidget.value()
            self.canvasRight.adjustSize()
            self.canvasRight.update()

    def adjustScale(self, initial=False):
        value = self.scalers[self.MANUAL_ZOOM if initial else self.zoomMode]()
        value = int(100 * value)
        self.zoomWidget.setValue(value)
        self.zoom_values[self.filename] = (self.zoomMode, value)

    #调整以适合window，可能要改
    def scaleFitWindow(self):
        """Figure out the size of the pixmap to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvasLeft.pixmap.width() - 0.0
        h2 = self.canvasLeft.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scaleFitWidth(self):
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvasLeft.pixmap.width()

    def enableSaveImageWithData(self, enabled):
        self._config["store_data"] = enabled
        self.actions.saveWithImageData.setChecked(enabled)

    def closeEvent(self, event):
        if not self.mayContinue():
            event.ignore()
        self.settings.setValue(
            "filename", self.filename if self.filename else ""
        )
        self.settings.setValue("window/size", self.size())
        self.settings.setValue("window/position", self.pos())
        self.settings.setValue("window/state", self.saveState())
        self.settings.setValue("recentFiles", self.recentFiles)
        # ask the use for where to save the labels
        # self.settings.setValue('window/geometry', self.saveGeometry())

    #拖拽进入事件，可以拖拽图片进入软件，但只能是在未打开图片时使用，如果有两个窗口显示，应该禁用或xxx
    def dragEnterEvent(self, event):
        extensions = [
            ".%s" % fmt.data().decode().lower()
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]
        if event.mimeData().hasUrls():
            items = [i.toLocalFile() for i in event.mimeData().urls()]
            if any([i.lower().endswith(tuple(extensions)) for i in items]):
                event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not self.mayContinue():
            event.ignore()
            return
        items = [i.toLocalFile() for i in event.mimeData().urls()]
        self.importDroppedImageFiles(items)

    # User Dialogs #

    def loadRecent(self, filename):
        if self.mayContinue():
            self.loadFileSelect(filename)

    #打开上张，和下边的打开下一张，这如果要是显示两个，那就都得修改
    def openPrevImg(self, _value=False, load=True):
        keep_prev = self._config["keep_prev"]
        if QtWidgets.QApplication.keyboardModifiers() == (
            Qt.ControlModifier | Qt.ShiftModifier
        ):
            self._config["keep_prev"] = True

        if not self.mayContinue():
            return

        if len(self.imageList) <= 0:
            return

        if self.filename is None:
            return

        currIndex = self.imageList.index(osp.basename(self.filename))
        if currIndex - 1 >= 0:
            filename = self.imageList[currIndex - 1]
            if filename and load:
                # self.loadFileSelect(filename)
                self.filename = filename
                fileNameDepth = self.filename[:self.filename.index('color')] + 'depth.png'
                self.loadFileSelect(os.path.join(self.lastOpenDir, self.filename),os.path.join(self.lastOpenDir, fileNameDepth))

        self._config["keep_prev"] = keep_prev

    #TODO 此处修改了原本的openNextImg，使得可以同时打开深度图和RGB图
    def openNextImg(self, _value=False, load=True):
        keep_prev = self._config["keep_prev"]
        if QtWidgets.QApplication.keyboardModifiers() == (
            Qt.ControlModifier | Qt.ShiftModifier
        ):
            self._config["keep_prev"] = True

        if not self.mayContinue():
            return

        if len(self.imageList) <= 0:
            return

        filename = None
        if self.filename is None:
            filename = self.imageList[0]
        else:
            currIndex = self.imageList.index(osp.basename(self.filename))
            if currIndex + 1 < len(self.imageList):
                filename = self.imageList[currIndex + 1]
            else:
                filename = self.imageList[-1]
        self.filename = filename

        if self.filename and load:
            fileNameDepth = self.filename[:self.filename.index('color')] + 'depth.png'
            # self.loadFileBoth(self.filename,fileNameDepth)
            self.loadFileSelect(os.path.join(self.lastOpenDir, self.filename),os.path.join(self.lastOpenDir, fileNameDepth))

        self._config["keep_prev"] = keep_prev


    #打开文件函数，要修改成对应两张图片的
    def openFile(self, _value=False):
        if not self.mayContinue():
            return
        path = osp.dirname(str(self.filename)) if self.filename else "."
        formats = [
            "*.{}".format(fmt.data().decode())
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]
        filters = self.tr("Image & Label files (%s)") % " ".join(
            formats
        )
        fileDialog = FileDialogPreview(self)
        fileDialog.setFileMode(FileDialogPreview.ExistingFile)
        fileDialog.setNameFilter(filters)
        fileDialog.setWindowTitle(
            self.tr("%s - Choose Image or Label file") % __appname__,
        )
        fileDialog.setWindowFilePath(path)
        fileDialog.setViewMode(FileDialogPreview.Detail)
        if fileDialog.exec_():
            fileName = fileDialog.selectedFiles()[0]
            if fileName.find('json')!=-1:
                self.errorMessage(
                    self.tr("Error: opening json file."), self.tr("<b>%s</b>") % filename
                )
                return False
            if fileName:
                if fileName[-9:] == 'color.jpg':
                    filenameRGB = fileName
                    if osp.exists(filenameRGB[:-9] + 'depth.png'):
                        filenameDepth = filenameRGB[:-9] + 'depth.png'
                    else:
                        filenameDepth = None

                elif fileName[-9:] == 'depth.png':
                    filenameDepth = fileName
                    if osp.exists(filenameDepth[:-9] + 'color.jpg'):
                        filenameRGB = filenameDepth[:-9] + 'color.jpg'
                    else:
                        filenameRGB = None
                self.loadFileSelect(filenameRGB, filenameDepth)


    def changeOutputDirDialog(self, _value=False):
        default_output_dir = self.output_dir
        if default_output_dir is None and self.filename:
            default_output_dir = osp.dirname(self.filename)
        if default_output_dir is None:
            default_output_dir = self.currentPath()

        output_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            self.tr("%s - Save/Load Annotations in Directory") % __appname__,
            default_output_dir,
            QtWidgets.QFileDialog.ShowDirsOnly
            | QtWidgets.QFileDialog.DontResolveSymlinks,
        )
        output_dir = str(output_dir)

        if not output_dir:
            return

        self.output_dir = output_dir

        self.statusBar().showMessage(
            self.tr("%s . Annotations will be saved/loaded in %s")
            % ("Change Annotations Dir", self.output_dir)
        )
        self.statusBar().show()

        current_filename = self.filename
        self.importDirImages(self.lastOpenDir, load=False)

        if current_filename in self.imageList:
            # retain currently selected file
            self.fileListWidget.setCurrentRow(
                self.imageList.index(current_filename)
            )
            self.fileListWidget.repaint()

    #保存文件系列函数，要同时保存两张图片对应的json？
    # TODO 保存文件函数，要保存成xxxxxxlabel，格式符合文档
    def saveFile(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        if self.labelFile:
            # DL20180323 - overwrite when in directory
            self._saveFile(self.labelFile.filename)
        elif self.output_file:
            self._saveFile(self.output_file)
            self.close()
        else:
            self._saveFile(self.saveFileDialog())

    def saveFileAs(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._saveFile(self.saveFileDialog())

    def saveFileDialog(self):
        caption = self.tr("%s - Choose File") % __appname__
        filters = self.tr("Label files (*%s)") % LabelFile.suffix
        if self.output_dir:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.output_dir, filters
            )
        else:
            dlg = QtWidgets.QFileDialog(
                self, caption, self.currentPath(), filters
            )
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dlg.setOption(QtWidgets.QFileDialog.DontConfirmOverwrite, False)
        dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, False)
        basename = osp.basename(osp.splitext(self.filename)[0])
        if self.output_dir:
            default_labelfile_name = osp.join(
                self.output_dir, basename + LabelFile.suffix
            )
        else:
            default_labelfile_name = osp.join(
                self.currentPath(), basename + LabelFile.suffix
            )
        filename = dlg.getSaveFileName(
            self,
            self.tr("Choose File"),
            default_labelfile_name,
            self.tr("Label files (*%s)") % LabelFile.suffix,
        )
        if isinstance(filename, tuple):
            filename, _ = filename
        return filename

    def _saveFile(self, filename):
        if filename and self.saveLabels(filename,self.saveMode):
            self.addRecentFile(filename)
            self.setClean()

    def closeFile(self, _value=False):
        if not self.mayContinue():
            return
        self.resetState()
        self.setClean()
        self.toggleActions(False)
        self.canvasLeft.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def getLabelFile(self):
        if self.filename.lower().endswith(".json"):
            label_file = self.filename
        else:
            label_file = osp.splitext(self.filename)[0] + ".json"

        return label_file

    def deleteFile(self):
        mb = QtWidgets.QMessageBox
        msg = self.tr(
            "You are about to permanently delete this label file, "
            "proceed anyway?"
        )
        answer = mb.warning(self, self.tr("Attention"), msg, mb.Yes | mb.No)
        if answer != mb.Yes:
            return

        label_file = self.getLabelFile()
        if osp.exists(label_file):
            os.remove(label_file)
            logger.info("Label file is removed: {}".format(label_file))

            item = self.fileListWidget.currentItem()
            item.setCheckState(Qt.Unchecked)

            self.resetState()

    # Message Dialogs. #
    def hasLabels(self):
        if self.noShapes():
            self.errorMessage(
                "No objects labeled",
                "You must label at least one object to save the file.",
            )
            return False
        return True

    def hasLabelFile(self):
        if self.filename is None:
            return False

        label_file = self.getLabelFile()
        return osp.exists(label_file)

    def mayContinue(self):
        if not self.dirty:
            return True
        mb = QtWidgets.QMessageBox
        msg = self.tr('Save annotations to "{}" before closing?').format(
            self.filename
        )
        answer = mb.question(
            self,
            self.tr("Save annotations?"),
            msg,
            mb.Save | mb.Discard | mb.Cancel,
            mb.Save,
        )
        if answer == mb.Discard:
            return True
        elif answer == mb.Save:
            self.saveFile()
            return True
        else:  # answer == mb.Cancel
            return False

    def errorMessage(self, title, message):
        return QtWidgets.QMessageBox.critical(
            self, title, "<p><b>%s</b></p>%s" % (title, message)
        )
    
    def warningMessage(self, title, message):
        return QtWidgets.QMessageBox.warning(
            self, title, "<p><b>%s</b></p>%s" % (title, message)
        )

    def currentPath(self):
        return osp.dirname(str(self.filename)) if self.filename else "."

    def toggleKeepPrevMode(self):
        self._config["keep_prev"] = not self._config["keep_prev"]

    def removeSelectedPoint(self):
        self.canvasLeft.removeSelectedPoint()
        self.canvasLeft.update()
        if not self.canvasLeft.hShape.points:
            self.canvasLeft.deleteShape(self.canvasLeft.hShape)
            self.remLabels([self.canvasLeft.hShape])
            self.setDirty()
            if self.noShapes():
                for action in self.actions.onShapesPresent:
                    action.setEnabled(False)

    #FIXME 删除有bug
   #对于shape的修改都要两个窗口复制，这是删除所选shape
    def deleteSelectedShape(self):
        if self.nowFocus=='RGB':
            yes, no = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No
            msg = self.tr(
                "You are about to permanently delete {} polygons, "
                "proceed anyway?"
            ).format(len(self.canvasLeft.selectedShapes))
            if yes == QtWidgets.QMessageBox.warning(
                self, self.tr("Attention"), msg, yes | no, yes
            ):

                self.remLabels(self.canvasLeft.deleteSelected())
                self.setDirty()
                if self.noShapes():
                    for action in self.actions.onShapesPresent:
                        action.setEnabled(False)
        else:
            yes, no = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No
            msg = self.tr(
                "You are about to permanently delete {} polygons, "
                "proceed anyway?"
            ).format(len(self.canvasRight.selectedShapes))
            if yes == QtWidgets.QMessageBox.warning(
                    self, self.tr("Attention"), msg, yes | no, yes
            ):

                self.remLabels(self.canvasRight.deleteSelected())
                self.setDirty()
                if self.noShapes():
                    for action in self.actions.onShapesPresent:
                        action.setEnabled(False)

    def copyShape(self):
        self.canvasLeft.endMove(copy=True)
        for shape in self.canvasLeft.selectedShapes:
            self.addLabelColor(shape)
        for shape in self.canvasRight.selectedShapes:
            self.addLabelDepth(shape)
        self.labelListColor.clearSelection()
        self.labelListDepth.clearSelection()
        self.setDirty()

    def moveShape(self):
        self.canvasLeft.endMove(copy=False)
        self.setDirty()

    def openDirDialog(self, _value=False, dirpath=None):
        if not self.mayContinue():
            return

        defaultOpenDirPath = dirpath if dirpath else "."
        if self.lastOpenDir and osp.exists(self.lastOpenDir):
            defaultOpenDirPath = self.lastOpenDir
        else:
            defaultOpenDirPath = (
                osp.dirname(self.filename) if self.filename else "."
            )

        targetDirPath = str(
            QtWidgets.QFileDialog.getExistingDirectory(
                self,
                self.tr("%s - Open Directory") % __appname__,
                defaultOpenDirPath,
                QtWidgets.QFileDialog.ShowDirsOnly
                | QtWidgets.QFileDialog.DontResolveSymlinks,
            )
        )
        self.importDirImagesRGB(targetDirPath)

    @property
    def imageList(self):
        lst = []
        for i in range(self.fileListWidget.count()):
            item = self.fileListWidget.item(i)
            lst.append(item.text())
        return lst

    def importDroppedImageFiles(self, imageFiles):
        extensions = [
            ".%s" % fmt.data().decode().lower()
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]

        self.filename = None
        for file in imageFiles:
            if file in self.imageList or not file.lower().endswith(
                tuple(extensions)
            ):
                continue
            label_file = osp.splitext(file)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = osp.join(self.output_dir, label_file_without_path)
            fileBasename = osp.basename(file)
            self.lastOpenDir = file.replace(fileBasename, "")
            item = QtWidgets.QListWidgetItem(fileBasename)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
                label_file
            ):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.fileListWidget.addItem(item)

        if len(self.imageList) > 1:
            self.actions.openNextImg.setEnabled(True)
            self.actions.openPrevImg.setEnabled(True)

        self.openNextImg()


    #导入一个dir的图片，这个可以改，来读取深度和普通
    #TODO 2222222222222222222222导入一个dir的图片
    def importDirImagesRGB(self, dirpath, pattern=None, load=True):
        self.actions.openNextImg.setEnabled(True)
        self.actions.openPrevImg.setEnabled(True)

        if not self.mayContinue() or not dirpath:
            return

        self.lastOpenDir = dirpath
        self.filename = None
        self.fileListWidget.clear()
        for filename in self.scanAllImages(dirpath):
            a=filename.find('color')
            if filename.find('color')!=-1:
                if pattern and pattern not in filename:
                    continue
                RGB_file = osp.splitext(filename)[0]
                label_file = RGB_file[:RGB_file.find('color')]+ "label.json"
                if self.output_dir:
                    label_file_without_path = osp.basename(label_file)
                    label_file = osp.join(self.output_dir, label_file_without_path)
                item = QtWidgets.QListWidgetItem(os.path.basename(filename))  # only show the basename path
                # item = QtWidgets.QListWidgetItem(filename)  
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
                    label_file
                ):
                    item.setCheckState(Qt.Checked)
                else:
                    item.setCheckState(Qt.Unchecked)
                self.fileListWidget.addItem(item)
        self.openNextImg(load=load)


    def importDirImages(self, dirpath, pattern=None, load=True):
        self.actions.openNextImg.setEnabled(True)
        self.actions.openPrevImg.setEnabled(True)

        if not self.mayContinue() or not dirpath:
            return

        self.lastOpenDir = dirpath
        self.filename = None
        self.fileListWidget.clear()
        for filename in self.scanAllImages(dirpath):
            if pattern and pattern not in filename:
                continue
            label_file = osp.splitext(filename)[0] + ".json"
            if self.output_dir:
                label_file_without_path = osp.basename(label_file)
                label_file = osp.join(self.output_dir, label_file_without_path)
            item = QtWidgets.QListWidgetItem(filename)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if QtCore.QFile.exists(label_file) and LabelFile.is_label_file(
                label_file
            ):
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.fileListWidget.addItem(item)
        self.openNextImg(load=load)


    #用来扫描这个文件夹里的所有图片，可以改造来分开深度和普通图
    def scanAllImages(self, folderPath):
        extensions = [
            ".%s" % fmt.data().decode().lower()
            for fmt in QtGui.QImageReader.supportedImageFormats()
        ]

        images = []
        for root, dirs, files in os.walk(folderPath):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relativePath = osp.join(root, file)
                    images.append(relativePath)
        images = natsort.os_sorted(images)
        return images
