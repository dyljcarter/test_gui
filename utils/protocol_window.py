from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QCheckBox,
    QGroupBox,
)
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg
import numpy as np


class ProtocolWindow(QMainWindow):
    """
    Main protocol window. Receives:
      - daq_receiver : DAQReceiver thread (running or to be started)
      - selected_channels : list of ints
      - mvc_values : dict {channel: mvc}
      - offsets : dict {channel: offset}
    """

    def __init__(
        self, daq_receiver, selected_channels, mvc_values, offsets, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle("DAQ + Force Protocol GUI")
        self.setGeometry(100, 100, 1400, 700)

        self.daq = daq_receiver
        self.selected_channels = selected_channels or []
        self.mvc_values = mvc_values or {}
        self.offsets = offsets or {}

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout()
        main_widget.setLayout(main_layout)

        # Left: protocol configuration
        left_panel = QWidget()
        left_panel_layout = QVBoxLayout()
        left_panel.setLayout(left_panel_layout)
        left_panel.setMaximumWidth(320)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.entries_layout = QVBoxLayout()
        scroll_widget.setLayout(self.entries_layout)
        scroll.setWidget(scroll_widget)
        left_panel_layout.addWidget(scroll)

        btn_layout = QVBoxLayout()
        add_btn = QPushButton("Add Point")
        add_btn.clicked.connect(self.add_entry_box)
        btn_layout.addWidget(add_btn)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_animation)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_animation)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        left_panel_layout.addLayout(btn_layout)
        main_layout.addWidget(left_panel)

        # Center plot
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#2b2b2b")
        self.plot_widget.setLabel(
            "left", "% MVC / Signal", **{"color": "#FFFFFF", "font-size": "12pt"}
        )
        self.plot_widget.setLabel(
            "bottom", "Time (s)", **{"color": "#FFFFFF", "font-size": "12pt"}
        )
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        main_layout.addWidget(self.plot_widget)

        # Right: channel control & DAQ control
        right_panel = QWidget()
        right_panel_layout = QVBoxLayout()
        right_panel.setLayout(right_panel_layout)
        right_panel.setMaximumWidth(250)

        daq_group = QGroupBox("DAQ Control")
        daq_layout = QVBoxLayout()
        self.connect_daq_btn = QPushButton("Connect DAQ")
        self.connect_daq_btn.clicked.connect(self.connect_daq)
        daq_layout.addWidget(self.connect_daq_btn)

        self.disconnect_daq_btn = QPushButton("Disconnect DAQ")
        self.disconnect_daq_btn.clicked.connect(self.disconnect_daq)
        self.disconnect_daq_btn.setEnabled(False)
        daq_layout.addWidget(self.disconnect_daq_btn)

        daq_group.setLayout(daq_layout)
        right_panel_layout.addWidget(daq_group)

        channel_group = QGroupBox("AUX Channels")
        channel_scroll = QScrollArea()
        channel_scroll.setWidgetResizable(True)
        channel_widget = QWidget()
        self.channel_layout = QVBoxLayout()
        channel_widget.setLayout(self.channel_layout)
        channel_scroll.setWidget(channel_widget)

        self.channel_checkboxes = []
        for i in range(16):
            cb = QCheckBox(f"AUX Channel {i}")
            cb.stateChanged.connect(self.update_channel_visibility)
            cb.setChecked(i in self.selected_channels)
            self.channel_checkboxes.append(cb)
            self.channel_layout.addWidget(cb)

        channel_group_layout = QVBoxLayout()
        channel_group_layout.addWidget(channel_scroll)
        channel_group.setLayout(channel_group_layout)
        right_panel_layout.addWidget(channel_group)

        right_panel_layout.addStretch()
        main_layout.addWidget(right_panel)

        # Internal variables
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)
        self.current_time = 0.0
        self.time_window = 10.0
        self.is_animating = False
        self.points = []
        self.entry_boxes = []

        # DAQ data handling
        self.daq.data_received.connect(self.update_aux_data)
        self.aux_data = [np.array([]) for _ in range(16)]
        self.aux_curves = []
        self.protocol_curve = None

        colors = [pg.intColor(i, 16) for i in range(16)]
        for i in range(16):
            curve = self.plot_widget.plot(
                [], [], pen=pg.mkPen(color=colors[i], width=2), name=f"AUX {i}"
            )
            visible = i in self.selected_channels
            curve.setVisible(visible)
            self.aux_curves.append(curve)

        # default protocol points can be created via add_entry_box if desired
        self.sample_rate = 500

    def connect_daq(self):
        try:
            if not self.daq.isRunning():
                self.daq.start()
            self.connect_daq_btn.setEnabled(False)
            self.disconnect_daq_btn.setEnabled(True)
        except Exception as e:
            print(f"Failed to start DAQ: {e}")

    def disconnect_daq(self):
        try:
            self.daq.stop()
            self.daq.wait()
            self.connect_daq_btn.setEnabled(True)
            self.disconnect_daq_btn.setEnabled(False)
        except Exception as e:
            print(f"Failed to stop DAQ: {e}")

    def update_aux_data(self, aux_signals):
        # aux_signals shape (16, N)
        for i in range(16):
            data = aux_signals[i, :].astype(np.float64)
            # subtract offset if known
            data = data - self.offsets.get(i, 0.0)
            mvc = self.mvc_values.get(i, None)
            if mvc and mvc > 0:
                percent = (data / mvc) * 100.0
            else:
                percent = data  # fallback: raw units
            self.aux_data[i] = np.append(self.aux_data[i], percent)
            max_samples = 30000
            if len(self.aux_data[i]) > max_samples:
                self.aux_data[i] = self.aux_data[i][-max_samples:]

        self.update_aux_plots()

    def update_aux_plots(self):
        sample_rate = self.sample_rate
        for i in range(16):
            if self.channel_checkboxes[i].isChecked() and len(self.aux_data[i]) > 0:
                time_axis = np.arange(len(self.aux_data[i])) / sample_rate
                if self.is_animating:
                    time_axis = time_axis + (
                        self.current_time - len(self.aux_data[i]) / sample_rate
                    )
                self.aux_curves[i].setData(time_axis, self.aux_data[i])

    def update_channel_visibility(self):
        for i, cb in enumerate(self.channel_checkboxes):
            self.aux_curves[i].setVisible(cb.isChecked())

    def add_entry_box(self):
        # Placeholder implementation to allow adding protocol points if needed.
        # The original EntryBox class from your script can be ported here.
        label = QLabel("Protocol point (add ported EntryBox here)")
        self.entries_layout.addWidget(label)

    def start_animation(self):
        self.is_animating = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.animation_timer.start(50)

    def update_animation(self):
        if not self.is_animating:
            return
        self.current_time += 0.05
        x_start = self.current_time - self.time_window / 2
        x_end = self.current_time + self.time_window / 2
        self.plot_widget.setXRange(x_start, x_end, padding=0)

    def stop_animation(self):
        self.is_animating = False
        self.animation_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        try:
            self.daq.stop()
        except Exception:
            pass
        event.accept()
