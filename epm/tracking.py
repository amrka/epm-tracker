# Tracking Dialog/widgets go here.
import os
from time import gmtime, strftime

import numpy as np
import pandas as pd
from skimage.draw import polygon

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from _tracking import (
    calc_background_image,
    threshold_image,
    get_otsu_threshold,
    convert_img_to_uint8,
    find_mouse
)
import _tracking

from utils import (
    get_q_image,
    get_mouse_coords
)


class Tracker(QObject):
    progress = pyqtSignal(int)
    def __init__(self, video, tracking_settings, parent=None):
        super(Tracker, self).__init__(parent)
        self.video = video
        self.tracking_settings = tracking_settings

    def track_video(self):
        b_img = calc_background_image(
            self.video,
            n_frames=self.tracking_settings.background_n_frames)

        props = []
        for ix in xrange(self.video.get_n_frames()):
            img, _ = self.video.get_frame(ix)
            props.append(
                find_mouse(img, b_img, threshold=self.tracking_settings.threshold)
                )
            self.progress.emit(ix)

        return props


class TrackingSettings:
    """
    Parameters
    ----------
    threshold : int, optional
        Threshold for detecting mouse after background subtraction.

    background_n_frames : int, optional (default=200)
        How many frames to use to calculate background image.

    inclusion_mask : np.array, optional
        Which region of the image should be included in tracking.

    inclusion_mask_filename : string, optional
        File that contains information about inclusion_mask.

    save_filename : string, optional
        Where to save
    """
    def __init__(self, threshold=None, background_n_frames=200, exclusion_mask=None,
        exculsion_mask_filename=None, save_filename=None):
        self.threshold = threshold
        self.background_n_frames = background_n_frames
        self.inclusion_mask = exclusion_mask
        self.inclusion_mask_filename = exculsion_mask_filename
        self.save_filename = save_filename


class MaskPoint(QGraphicsItem):
    def __init__(self, ellipse_x, ellipse_y, ellipse_width, color,
        text='', parent=None):
        super(MaskPoint, self).__init__(parent)

        self.color = color
        self.text = text

        self.ellipse_width = self.ellipse_height = ellipse_width
        self.ellipse_x = ellipse_x
        self.ellipse_y = ellipse_y

        self.bounding_rect_x = self.ellipse_x - 0.5 * self.ellipse_width
        self.bounding_rect_y = self.ellipse_y - 0.5 * self.ellipse_width
        self.bounding_rect_width = self.ellipse_width
        self.bounding_rect_height = self.ellipse_height

        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setFlag(QGraphicsItem.ItemIsMovable)

    def boundingRect(self):
        return QRectF(self.bounding_rect_x, self.bounding_rect_y,
            self.bounding_rect_width, self.bounding_rect_height)

    def paint(self, painter, option, widget):
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(self.ellipse_x - 0.5 * self.ellipse_width,
            self.ellipse_y - 0.5 * self.ellipse_height,
            self.ellipse_width, self.ellipse_height)


class MaskWidget(QWidget):
    """Widget to manage setting of mask for EPM."""
    def __init__(self, video, tracking_settings, parent=None):
        super(MaskWidget, self).__init__(parent)
        self.video = video
        self.tracking_settings = tracking_settings

        self.set_graphics_scene_ui()
        self.set_mask_image_ui()

        layout=QGridLayout()
        layout.addWidget(self.mask_image_groupbox, 0, 0, 4, 1)
        layout.addWidget(self.graphics_scene_groupbox, 0, 1, 2, 1)
        self.setLayout(layout)

    def set_graphics_scene_ui(self):
        self.graphics_scene_groupbox = QGroupBox()
        layout = QGridLayout()

        self.graphics_scene = QGraphicsScene()
        #background image
        self.graphics_scene_pixmap = self.graphics_scene.addPixmap(
            QPixmap.fromImage(get_q_image(self.video.get_frame(0)[0]))
        )
        self.graphics_scene_view = QGraphicsView(self.graphics_scene)

        self.initial_mask_point_locations = np.array([
            [self.video.get_width()/4, 0],
            [self.video.get_width()/2, self.video.get_height()/3],
            [self.video.get_width()/4*3, 0],

            [self.video.get_width(), self.video.get_height()/4],
            [self.video.get_width()/3*2, self.video.get_height()/2],
            [self.video.get_width(), self.video.get_height()/4*3],

            [self.video.get_width()/4, self.video.get_height()],
            [self.video.get_width()/2, self.video.get_height()/3*2],
            [self.video.get_width()/4*3, self.video.get_height()],

            [0, self.video.get_height()/4],
            [self.video.get_width()/3, self.video.get_height()/2],
            [0, self.video.get_height()/4*3]
        ])
        point_colors = [Qt.blue, Qt.darkBlue, Qt.blue, Qt.green, Qt.darkGreen,
            Qt.green, Qt.cyan, Qt.darkCyan, Qt.cyan, Qt.magenta, Qt.darkMagenta,
            Qt.magenta]

        self.mask_points = [
            MaskPoint(self.initial_mask_point_locations[i, 0],
                self.initial_mask_point_locations[i, 1],
                10, point_colors[i], '') for i in xrange(len(point_colors))
        ]
        for mask_point in self.mask_points:
            self.graphics_scene.addItem(mask_point)

        self.generate_mask_button = QPushButton('Update Mask')
        self.generate_mask_button.clicked.connect(self.generate_mask)
        self.load_mask_button = QPushButton('Load Mask')
        self.save_mask_button = QPushButton('Save Mask')

        layout.addWidget(self.graphics_scene_view, 0, 0, 5, 5)
        layout.addWidget(self.generate_mask_button, 5, 4, 1, 1)
        layout.addWidget(self.load_mask_button, 6, 0, 1, 1)
        layout.addWidget(self.save_mask_button, 6, 1, 1, 1)

        self.graphics_scene_groupbox.setLayout(layout)

    def set_mask_image_ui(self):
        self.mask_image_groupbox = QGroupBox('EPM Arena Mask')
        layout = QVBoxLayout()

        self.arena_image, _ = self.video.get_frame(0)
        self.mask_image = np.zeros_like(self.arena_image).astype(np.uint8)
        self.arena_with_mask_image = np.zeros_like(
            self.arena_image).astype(np.uint8)

        self.arena_image_label = QLabel()
        self.mask_image_label = QLabel()
        self.arena_with_mask_image_label = QLabel()

        self.update_arena_image_label()
        self.update_mask_image_label()
        self.update_arena_with_mask_image_label()

        layout.addWidget(self.arena_image_label)
        layout.addWidget(self.mask_image_label)
        layout.addWidget(self.arena_with_mask_image_label)
        self.mask_image_groupbox.setLayout(layout)

    @pyqtSlot()
    def generate_mask(self):

        central_rs, central_cs = 0, 0
        global_point_pos = np.zeros(shape=(len(self.mask_points), 2))
        # collect all of the mask points, generate global coords,
        # and find the center of mass of the points (center of the arena).
        for i, mask_point in enumerate(self.mask_points):
            # transform coords w.r.t. graphics_scene_pixmap
            point_pos = np.array([mask_point.y(), mask_point.x()])
            global_point_pos[i, :] = (
                np.array([mask_point.ellipse_y, mask_point.ellipse_x]) +
                point_pos
                )
            central_rs += global_point_pos[i, 0]
            central_cs += global_point_pos[i, 1]

        central_point = np.array([
            central_rs / global_point_pos.shape[0],
            central_cs / global_point_pos.shape[0]])

        # get coordinates such that they are all relative to the central point
        relative_point_pos = global_point_pos - central_point
        # sort the mask_points based on angle made with center of image.
        angles = np.arctan2(relative_point_pos[:, 0], relative_point_pos[:, 1])
        sorted_polygon_points = relative_point_pos[np.argsort(angles)]

        # place coordinates back into global positions for mask drawing.
        sorted_polygon_points += central_point
        # add first point onto end of points list to form closed polygon
        sorted_polygon_points = np.vstack((sorted_polygon_points,
            sorted_polygon_points[-1, :]))
        mask = np.zeros_like(self.arena_image)
        rr, cc = polygon(sorted_polygon_points[:, 0],
            sorted_polygon_points[:, 1], shape=self.arena_image.shape)
        mask[rr, cc] = 1
        # set this mask as the inclusion mask in our tracking_settings dict.
        self.tracking_settings.inclusion_mask = mask

        self.mask_image = convert_img_to_uint8(mask)

        self.arena_with_mask_image = self.arena_image
        self.arena_with_mask_image[~mask.astype(np.bool)] = 0

        self.update_mask_image_label()
        self.update_arena_with_mask_image_label()

    def update_arena_image_label(self):
        self.arena_image_label.setPixmap(
            QPixmap.fromImage(get_q_image(self.arena_image))
        )

    def update_mask_image_label(self):
        # TODO: update mask here.
        self.mask_image_label.setPixmap(
            QPixmap.fromImage(get_q_image(self.mask_image))
        )

    def update_arena_with_mask_image_label(self):
        # TODO: update arena_with_mask_image here
        self.arena_with_mask_image_label.setPixmap(
            QPixmap.fromImage(get_q_image(self.arena_with_mask_image))
        )

class ThresholdWidget(QWidget):
    def __init__(self, video, tracking_settings, parent=None):
        super(ThresholdWidget, self).__init__(parent)
        self.video = video
        self.frame_number = 0

        self.tracking_settings = tracking_settings

        self.setup_image_groupbox_ui()
        self.setup_input_groupbox_ui()
        self.setup_frame_number_groupbox_ui()
        # self.setup_track_button_groupbox_ui()

        layout = QGridLayout()

        layout.addWidget(self.image_groupbox, 0, 0, 3, 1)
        layout.addWidget(self.input_groupbox, 0, 1, 1, 1)
        layout.addWidget(self.frame_number_groupbox, 1, 1, 1, 1)
        # layout.addWidget(self.track_button_groupbox, 2, 1, 1, 1)
        self.setLayout(layout)

        self.tracking_settings.threshold = get_otsu_threshold(
            self.raw_image, self.background_image
        )

    def setup_image_groupbox_ui(self):
        """Setups image_groupbox with three images, which
        represent the first, raw image of the video. The calculated
        background image, and the thresholded image."""
        self.image_groupbox = QGroupBox('Images')

        layout = QVBoxLayout()

        self.raw_image, _ = self.video.get_frame(0)
        self.background_image = calc_background_image(
            self.video, self.tracking_settings.background_n_frames)
        self.thresholded_image = convert_img_to_uint8(
            threshold_image(self.raw_image,
                self.background_image, self.tracking_settings.threshold)
            )

        self.raw_image_label = QLabel()
        self.background_image_label = QLabel()
        self.threshold_image_label = QLabel()

        raw_image_pixmap = QPixmap.fromImage(get_q_image(self.raw_image))
        background_image_pixmap = QPixmap.fromImage(
            get_q_image(self.background_image))
        threshold_image_pixmap = QPixmap.fromImage(
            get_q_image(self.thresholded_image))

        self.raw_image_label.setPixmap(raw_image_pixmap)
        self.background_image_label.setPixmap(background_image_pixmap)
        self.threshold_image_label.setPixmap(threshold_image_pixmap)

        layout.addWidget(self.background_image_label)
        layout.addWidget(self.raw_image_label)
        layout.addWidget(self.threshold_image_label)

        self.image_groupbox.setLayout(layout)

    def setup_input_groupbox_ui(self):
        self.input_groupbox = QGroupBox('Tracking Settings')

        layout = QGridLayout()
        threshold_name_label = QLabel('Set threshold: ')
        background_n_frames_label = QLabel(
            'N of frames to calculate background: ')
        save_filename_label = QLabel('Save filename (.xlsx): ')

        layout.addWidget(threshold_name_label, 0, 0, 1, 1)
        layout.addWidget(background_n_frames_label, 1, 0, 1, 1)
        layout.addWidget(save_filename_label, 2, 0, 1, 1)

        self.threshold_spin_box = QSpinBox()
        self.threshold_spin_box.setMinimum(0)
        self.threshold_spin_box.setMaximum(100)
        self.threshold_spin_box.setValue(
            get_otsu_threshold(self.raw_image, self.background_image) * 100
        )
        self.threshold_spin_box.valueChanged.connect(
            self.update_threshold_image)

        self.background_frames_spinbox = QSpinBox()
        self.background_frames_spinbox.setMinimum(0)
        self.background_frames_spinbox.setMaximum(
            self.video.get_n_frames()
        )
        self.background_frames_spinbox.setValue(
            self.tracking_settings.background_n_frames
        )
        self.background_frames_spinbox.valueChanged.connect(
            self.update_background_image)

        self.save_filename_lineedit = QLineEdit()
        self.save_filename_lineedit.setText('Save name (.xlsx)')
        self.save_filename_lineedit.setReadOnly(True)
        self.save_filename_browse_button = QPushButton('Browse')
        self.save_filename_browse_button.clicked.connect(self.set_save_file)

        layout.addWidget(self.threshold_spin_box, 0, 1, 1, 1)
        layout.addWidget(self.background_frames_spinbox, 1, 1, 1, 1)
        layout.addWidget(self.save_filename_lineedit, 2, 1, 1, 2)
        layout.addWidget(self.save_filename_browse_button, 2, 3, 1, 1)

        self.input_groupbox.setLayout(layout)

    def setup_frame_number_groupbox_ui(self):
        self.frame_number_groupbox = QGroupBox('Jump to Frame')

        layout = QGridLayout()

        self.frame_number_slider = QSlider(Qt.Horizontal)
        self.frame_number_slider.setMaximum(self.video.get_n_frames() - 1)
        self.frame_number_slider.valueChanged.connect(
            self.update_images)

        self.frame_number_spinbox = QSpinBox()
        self.frame_number_spinbox.setMinimum(0)
        self.frame_number_spinbox.setMaximum(self.video.get_n_frames() - 1)
        self.frame_number_spinbox.valueChanged.connect(
            self.update_images)

        self.random_frame_button = QPushButton('Random Frame')
        self.random_frame_button.clicked.connect(self.update_random_frame)

        layout.addWidget(self.frame_number_slider, 0, 0, 1, 3)
        layout.addWidget(self.frame_number_spinbox, 1, 0, 1, 1)
        layout.addWidget(self.random_frame_button, 2, 0, 1, 1)

        self.frame_number_groupbox.setLayout(layout)
    #
    # def setup_track_button_groupbox_ui(self):
    #     self.track_button_groupbox = QGroupBox('Begin Tracking')
    #     layout = QGridLayout()
    #
    #     self.track_button = QPushButton('Track')
    #     layout.addWidget(QLabel('\t'*4), 0, 0, 1, 3)
    #     layout.addWidget(QLabel('\t'*4), 1, 0, 1, 3)
    #     layout.addWidget(QLabel('\t'*4), 2, 0, 1, 3)
    #     layout.addWidget(self.track_button, 3, 3, 1, 1)
    #     self.track_button_groupbox.setLayout(layout)

    @pyqtSlot()
    def set_save_file(self):
        file_dialog = QFileDialog(self)
        tracking_savefile = str(file_dialog.getSaveFileName(
            caption='Save File',
            filter='Spreadsheet (*.xlsx)'
            ))
        if tracking_savefile != '':
            self.tracking_settings.save_filename = tracking_savefile
            self.save_filename_lineedit.setText(tracking_savefile)

    @pyqtSlot()
    def update_random_frame(self):
        random_ix = np.random.randint(0, self.video.get_n_frames())
        self.update_images(random_ix)

    @pyqtSlot(int)
    def update_images(self, frame_ix):
        self.frame_number = frame_ix

        if self.frame_number_spinbox.value() != frame_ix:
            self.frame_number_spinbox.setValue(frame_ix)

        if self.frame_number_slider.value() != frame_ix:
            self.frame_number_slider.setValue(frame_ix)

        self.update_raw_image(frame_ix)
        self.update_threshold_image(self.tracking_settings.threshold * 100)

    @pyqtSlot(int)
    def update_raw_image(self, frame_ix):
        self.raw_image, _ = self.video.get_frame(frame_ix)
        raw_image_pixmap = QPixmap.fromImage(get_q_image(self.raw_image))
        self.raw_image_label.setPixmap(raw_image_pixmap)

    @pyqtSlot(int)
    def update_background_image(self, n_frames):
        self.tracking_settings.background_n_frames = n_frames
        self.background_image = calc_background_image(
            self.video, self.tracking_settings.background_n_frames)
        background_image_pixmap = QPixmap.fromImage(
            get_q_image(self.background_image))
        self.background_image_label.setPixmap(background_image_pixmap)

    @pyqtSlot(int)
    def update_threshold_image(self, threshold):
        self.tracking_settings.threshold = threshold / 100.
        self.thresholded_image = convert_img_to_uint8(
            threshold_image(self.raw_image,
                self.background_image, self.tracking_settings.threshold)
            )
        threshold_image_pixmap = QPixmap.fromImage(
            get_q_image(self.thresholded_image))
        self.threshold_image_label.setPixmap(threshold_image_pixmap)

class TrackingDialog(QDialog):
    def __init__(self, video, parent=None):
        super(TrackingDialog, self).__init__(parent)
        self.video = video
        self.total_video_frames = video.get_n_frames()
        self.tracking_settings = TrackingSettings()

        self.video_tracker = Tracker(self.video, self.tracking_settings)
        self.video_tracker.progress.connect(self.update_progress_bar)

        self.setup_status_bar_ui()
        self.setup_ui()
        self.setWindowTitle('Tracking')

    def setup_ui(self):
        layout = QGridLayout()

        self.stacked_widget = QStackedWidget()
        self.threshold_widget = ThresholdWidget(
            self.video, self.tracking_settings)

        self.mask_widget = MaskWidget(self.video, self.tracking_settings)

        self.stacked_widget.addWidget(self.mask_widget)
        self.stacked_widget.addWidget(self.threshold_widget)

        self.next_button = QPushButton('>>')
        self.next_button.clicked.connect(self.next_stacked_widget)
        self.previous_button = QPushButton('<<')
        self.previous_button.clicked.connect(self.previous_stacked_widget)
        self.track_button = QPushButton('Begin Tracking')
        self.track_button.clicked.connect(self.track_video)

        layout.addWidget(self.stacked_widget, 0, 0, 4, 6)
        layout.addWidget(self.previous_button, 4, 0, 1, 1)
        layout.addWidget(self.next_button, 4, 1, 1, 1)
        layout.addWidget(self.track_button, 4, 2, 1, 1)
        layout.addWidget(self.status_bar, 5, 0, 1, 6)

        self.setLayout(layout)

    def setup_status_bar_ui(self):
        self.status_bar = QStatusBar()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(self.video.get_n_frames() - 1)

        self.stacked_widget_page = 1
        self.stacked_widget_page_label = QLabel('Page: 1/3')

        self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.addWidget(self.stacked_widget_page_label)

    @pyqtSlot()
    def next_stacked_widget(self):
        self.stacked_widget_page = self.stacked_widget.currentIndex()
        n_widgets_in_stack = self.stacked_widget.count()
        if self.stacked_widget_page + 1 < n_widgets_in_stack:
            self.stacked_widget_page += 1
        self.stacked_widget.setCurrentIndex(self.stacked_widget_page)

    @pyqtSlot()
    def previous_stacked_widget(self):
        self.stacked_widget_page = self.stacked_widget.currentIndex()
        if self.stacked_widget_page > 0:
            self.stacked_widget_page -= 1
        self.stacked_widget.setCurrentIndex(self.stacked_widget_page)

    @pyqtSlot(int)
    def update_progress_bar(self, progress):
        self.progress_bar.setValue(progress)
        QApplication.processEvents()

    @pyqtSlot()
    def track_video(self):
        self.props = self.video_tracker.track_video()

        tracking_data = pd.DataFrame()
        rr, cc = [], []
        maj, minor, area = [], [], []

        for prop in self.props:
            if prop == -1:
                rr.append(np.nan)
                cc.append(np.nan)
                maj.append(np.nan)
                minor.append(np.nan)
                area.append(np.nan)
                continue

            rr_, cc_ = prop.centroid
            rr.append(rr_)
            cc.append(cc_)
            maj.append(prop.major_axis_length)
            minor.append(prop.minor_axis_length)
            area.append(prop.area)

        tracking_data['rr'] = rr
        tracking_data['cc'] = cc
        tracking_data['area'] = area
        tracking_data['maj'] = maj
        tracking_data['min'] = minor

        if self.tracking_settings.save_filename is not None:
            tracking_data.to_excel(
                self.tracking_settings.save_filename,
                na_rep='NA',
                index_label='frame',
                sheet_name='RawData')
        else:
            savename = strftime("%a, %d %b %Y %H:%M:%S +0000", gmtime())
            savename += '.xlsx'
            tracking_data.to_excel(
                os.path.join(os.path.expanduser("~"), savename),
                na_rep='NA',
                index_label='frame',
                sheet_name='RawData')
