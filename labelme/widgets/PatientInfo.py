from qtpy import QtCore
from qtpy.QtCore import Qt
from qtpy import QtGui
from qtpy.QtGui import QPalette
from qtpy import QtWidgets
from qtpy.QtWidgets import QStyle


class PatientInfoWidget():
    def __init__(self):
        super(PatientInfoWidget, self).__init__()
        self.patientInfoWidget = QtWidgets.QWidget()

        # layout for each row
        self.pInfo_layout = QtWidgets.QVBoxLayout()
        self.pInfo_H_layout = QtWidgets.QHBoxLayout()
        self.pInfo_W_layout = QtWidgets.QHBoxLayout()
        self.pInfo_P_layout = QtWidgets.QHBoxLayout()
        self.pInfo_Pose = QtWidgets.QVBoxLayout()
        # self.InfoLabel=QtWidgets.QLabel(patientInfoWidget)
        # self.InfoLabel.setStyleSheet("QLabel{background:white;}"
        #                "QLabel{color:rgb(100,100,100,250);font-size:15px;font-weight:bold;font-family:Roman times;}"
        #                "QLabel:hover{color:rgb(100,100,100,120);}")
        # self.InfoLabel.setWordWrap(True)

        self.pInfoLabelH = QtWidgets.QLabel()
        self.pInfoLabelH.setText('Height:')

        self.pInfoLabelW = QtWidgets.QLabel()
        self.pInfoLabelW.setText('Weight:')

        self.pFileLabel = QtWidgets.QLabel()
        self.pFileLabel.setText("Image Path:")

        self.pCaliLabel = QtWidgets.QLabel()
        self.pCaliLabel.setText("Calibration File:")

        self.pPoseLabel = QtWidgets.QLabel()
        self.pPoseLabel.setText("Pose:")

        self.Pose_combo = QtWidgets.QComboBox()
        self.Pose_combo.addItem("HFS")
        self.Pose_combo.addItem("FFS")
        self.Pose_combo.addItem("HFP")
        self.Pose_combo.addItem("FFP")
        self.Pose_combo.addItem("HFS_Superman")
        self.Pose_combo.addItem("HFP_Superman")

        self.pInfo_P_layout.addWidget(self.pPoseLabel)
        self.pInfo_P_layout.addWidget(self.Pose_combo)
        self.pInfo_P_layout.setStretch(1, 3)

        self.pInfoTextH = QtWidgets.QTextEdit()
        self.pInfoTextW = QtWidgets.QTextEdit()
        self.pInfoTextW.setMaximumHeight(25)
        self.pInfoTextH.setMaximumHeight(25)

        self.pInfoTextHcm = QtWidgets.QLabel()
        self.pInfoTextHcm.setText("cm")

        self.pInfoLabelWkg = QtWidgets.QLabel()
        self.pInfoLabelWkg.setText("kg")

        self.pInfo_H_layout.addWidget(self.pInfoLabelH)
        self.pInfo_H_layout.addWidget(self.pInfoTextH)
        self.pInfo_H_layout.addWidget(self.pInfoTextHcm)
        self.pInfo_H_layout.setStretch(1, 3)

        self.pInfo_W_layout.addWidget(self.pInfoLabelW)
        self.pInfo_W_layout.addWidget(self.pInfoTextW)
        self.pInfo_W_layout.addWidget(self.pInfoLabelWkg)
        self.pInfo_W_layout.setStretch(1, 3)

        self.pInfo_H_widget = QtWidgets.QWidget()
        self.pInfo_W_widget = QtWidgets.QWidget()
        self.pInfo_Pose_widget = QtWidgets.QWidget()
        self.pInfo_H_widget.setLayout(self.pInfo_H_layout)
        self.pInfo_W_widget.setLayout(self.pInfo_W_layout)
        self.pInfo_Pose_widget.setLayout(self.pInfo_P_layout)

        self.pInfo_layout.addWidget(self.pFileLabel)
        self.pInfo_layout.addWidget(self.pInfo_H_widget)
        self.pInfo_layout.addWidget(self.pInfo_W_widget)
        self.pInfo_layout.addWidget(self.pInfo_Pose_widget)
        self.pInfo_layout.addWidget(self.pCaliLabel)
        self.Update = QtWidgets.QPushButton()
        self.Update.setText('Update Info')
        self.pInfo_layout.addWidget(self.Update)
        self.patientInfoWidget.setLayout(self.pInfo_layout)

    def PatientInfoDock(self):
        return self.patientInfoWidget

    def setPoseCombo(self, pose):

        poselist = ["HFS", "FFS", "HFP", "FFP", "HFS_Superman", "HFP_Superman"]
        for i in range(len(poselist)):
            if pose == poselist[i]:
                self.Pose_combo.setCurrentIndex(i)
                break


    def LoadInfo(self,data):
        imgPath = data.imagePath
        patientHeight = data.otherData["patientHeight"]
        patientWeight = data.otherData["patientWeight"]
        patientPose = data.otherData["patientPose"]
        if data.otherData["calibrationExist"]:
            calibration = 'Exist'
        else:
            calibration = 'Not Exist'

        self.pInfoTextH.setText(str(patientHeight))
        self.pInfoTextW.setText(str(patientWeight))
        self.setPoseCombo(patientPose)
        self.pFileLabel.setText('Image Path:{}'.format(imgPath))
        self.pCaliLabel.setText('Calibration File:{}'.format(calibration))
        self.pFileLabel.adjustSize()
        self.pCaliLabel.adjustSize()


