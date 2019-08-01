# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'magic_wand_dockwidget_base.ui'
#
# Created by: PyQt5 UI code generator 5.9.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_MagicwandDockWidgetBase(object):
    def setupUi(self, MagicwandDockWidgetBase):
        MagicwandDockWidgetBase.setObjectName("MagicwandDockWidgetBase")
        MagicwandDockWidgetBase.resize(342, 119)
        self.dockWidgetContents = QtWidgets.QWidget()
        self.dockWidgetContents.setObjectName("dockWidgetContents")
        self.gridLayout = QtWidgets.QGridLayout(self.dockWidgetContents)
        self.gridLayout.setObjectName("gridLayout")
        self.pushButton = QtWidgets.QPushButton(self.dockWidgetContents)
        self.pushButton.setObjectName("pushButton")
        self.gridLayout.addWidget(self.pushButton, 0, 0, 1, 1)
        self.label = QtWidgets.QLabel(self.dockWidgetContents)
        self.label.setObjectName("label")
        self.gridLayout.addWidget(self.label, 1, 1, 1, 1)
        self.label_3 = QtWidgets.QLabel(self.dockWidgetContents)
        self.label_3.setObjectName("label_3")
        self.gridLayout.addWidget(self.label_3, 1, 0, 1, 1)
        self.label_4 = QtWidgets.QLabel(self.dockWidgetContents)
        self.label_4.setObjectName("label_4")
        self.gridLayout.addWidget(self.label_4, 2, 0, 1, 1)
        self.label_5 = QtWidgets.QLabel(self.dockWidgetContents)
        self.label_5.setObjectName("label_5")
        self.gridLayout.addWidget(self.label_5, 2, 1, 1, 1)
        self.horizontalSlider_2 = QtWidgets.QSlider(self.dockWidgetContents)
        self.horizontalSlider_2.setOrientation(QtCore.Qt.Horizontal)
        self.horizontalSlider_2.setObjectName("horizontalSlider_2")
        self.gridLayout.addWidget(self.horizontalSlider_2, 2, 2, 1, 1)
        self.horizontalSlider = QtWidgets.QSlider(self.dockWidgetContents)
        self.horizontalSlider.setOrientation(QtCore.Qt.Horizontal)
        self.horizontalSlider.setObjectName("horizontalSlider")
        self.gridLayout.addWidget(self.horizontalSlider, 1, 2, 1, 1)
        self.label_2 = QtWidgets.QLabel(self.dockWidgetContents)
        self.label_2.setObjectName("label_2")
        self.gridLayout.addWidget(self.label_2, 1, 3, 1, 1)
        self.single_mode = QtWidgets.QCheckBox(self.dockWidgetContents)
        self.single_mode.setObjectName("single_mode")
        self.gridLayout.addWidget(self.single_mode, 0, 3, 1, 1)
        self.label_6 = QtWidgets.QLabel(self.dockWidgetContents)
        self.label_6.setObjectName("label_6")
        self.gridLayout.addWidget(self.label_6, 2, 3, 1, 1)
        self.layerComboBox = QtWidgets.QComboBox(self.dockWidgetContents)
        self.layerComboBox.setObjectName("layerComboBox")
        self.gridLayout.addWidget(self.layerComboBox, 0, 1, 1, 2)
        MagicwandDockWidgetBase.setWidget(self.dockWidgetContents)

        self.retranslateUi(MagicwandDockWidgetBase)
        QtCore.QMetaObject.connectSlotsByName(MagicwandDockWidgetBase)

    def retranslateUi(self, MagicwandDockWidgetBase):
        _translate = QtCore.QCoreApplication.translate
        MagicwandDockWidgetBase.setWindowTitle(_translate("MagicwandDockWidgetBase", "Magic Wand"))
        self.pushButton.setText(_translate("MagicwandDockWidgetBase", "Enable"))
        self.label.setText(_translate("MagicwandDockWidgetBase", "Fast"))
        self.label_3.setText(_translate("MagicwandDockWidgetBase", "Accuracy"))
        self.label_4.setText(_translate("MagicwandDockWidgetBase", "Color Threshold"))
        self.label_5.setText(_translate("MagicwandDockWidgetBase", "Ambiguous"))
        self.label_2.setText(_translate("MagicwandDockWidgetBase", "Precise"))
        self.single_mode.setText(_translate("MagicwandDockWidgetBase", "Single Mode"))
        self.label_6.setText(_translate("MagicwandDockWidgetBase", "Strict"))

