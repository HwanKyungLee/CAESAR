import sys
import os
import math
import datetime
import time
import json
import numpy as np
import pandas as pd
import pyqtgraph as pg
pg.setConfigOption('background', 'w')
pg.setConfigOption('foreground', 'k')
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.family'] = 'Malgun Gothic'
matplotlib.rcParams['axes.unicode_minus'] = False

# [PyQt6] Backend

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from matplotlib.ticker import ScalarFormatter


from scipy.optimize import curve_fit, least_squares, lsq_linear
from scipy.interpolate import interp1d
from scipy.signal import convolve
from scipy.signal import find_peaks
from scipy.stats import norm
from scipy.signal.windows import tukey
from scipy.ndimage import gaussian_filter1d
from numpy.polynomial import chebyshev



# [PyQt6] Modules
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, 
                             QProgressBar, QGroupBox, QLineEdit, QScrollArea, QDialog, 
                             QComboBox, QSplitter, QTabWidget, QDoubleSpinBox, QSpinBox, 
                             QCheckBox, QGridLayout, QInputDialog, QRadioButton, QButtonGroup,
                             QSplashScreen, QDialogButtonBox, QStackedWidget, QFormLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPixmap

from app_window import CAESARAnalyzer

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 1. Load splash image (High-res PNG is recommended over ico)
    # The image file must be located in the same directory as the script.
    splash_pixmap = QPixmap("Argos.png") 
    
    # 2. Create splash screen object and display it in the center
    splash = QSplashScreen(splash_pixmap, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    
    # 3. Show loading message
    splash.showMessage(
        "Loading CAESAR Pro V1.0 Engine...", 
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter, 
        Qt.GlobalColor.white # Text color (Change to black if background is bright)
    )
    
    # Process events to prevent the splash screen from freezing/turning white during load
    app.processEvents() 

    # 4. Initialize the heavy main engine and UI (Splash screen remains visible)
    ex = CAESARAnalyzer() # Note: You can rename this class to CAESARAnalyzer if you wish!
    
    # (Optional) Force the s
    # plash screen to remain visible for 1 second for aesthetics 
    # just in case the program loads too quickly.
    time.sleep(0.5)

    
    # 5. Show the main application window maximized
    ex.showMaximized()
    
    # 6. Naturally fade out/close the splash screen once the main window appears
    if 'splash' in locals():
        splash.finish(ex)
        
    sys.exit(app.exec())