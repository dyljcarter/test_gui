from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QScrollArea,
)
from PyQt5.QtCore import QTimer, pyqtSignal
import pyqtgraph as pg
import numpy as np


class MVCWindow(QMainWindow):
    """
    Window for offset removal and MVC collection.

    Signals:
      - mvc_collected(dict) : {channel_index: mvc_value}
      - finished(list, dict) : (selected_channels, offsets)
    """

    mvc_collected = pyqtSignal(dict)
    finished = pyqtSignal(list, dict)

    def __init__(self, daq_receiver, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MVC Collection")
        self.setGeometry(150, 150, 1000, 600)

        self.daq = daq_receiver
        self.offsets = {i: 0.0 for i in range(16)}
        self.mvc_values = {}

        widget = QWidget()
        self.setCentralWidget(widget)
        layout = QHBoxLayout()
        widget.setLayout(layout)

        # Left: controls
        left = QWidget()
        left.setFixedWidth(300)
        l_layout = QVBoxLayout()
        left.setLayout(l_layout)

        l_layout.addWidget(QLabel("AUX Channels"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        ch_widget = QWidget()
        ch_layout = QVBoxLayout()
        ch_widget.setLayout(ch_layout)
        scroll.setWidget(ch_widget)

        self.checkboxes = []
        for i in range(16):
            cb = QCheckBox(f"AUX {i}")
            cb.setChecked(i == 0)
            ch_layout.addWidget(cb)
            self.checkboxes.append(cb)

        l_layout.addWidget(scroll)

        self.remove_offset_btn = QPushButton("Remove Offset")
        self.remove_offset_btn.clicked.connect(self.remove_offset)
        l_layout.addWidget(self.remove_offset_btn)

        self.collect_btn = QPushButton("Collect MVC")
        self.collect_btn.clicked.connect(self.collect_mvc)
        l_layout.addWidget(self.collect_btn)

        self.status_label = QLabel("")
        l_layout.addWidget(self.status_label)
        l_layout.addStretch()

        layout.addWidget(left)

        # Right: plot
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#222222")
        self.plot_widget.addLegend()
        self.plot_widget.setLabel("left", "AUX value")
        self.plot_widget.setLabel("bottom", "Time (s)")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        layout.addWidget(self.plot_widget)

        self.curves = []
        colors = [pg.intColor(i, 16) for i in range(16)]
        for i in range(16):
            curve = self.plot_widget.plot(
                [], [], pen=pg.mkPen(colors[i], width=2), name=f"AUX{i}"
            )
            curve.setVisible(False)
            self.curves.append(curve)

        # Live buffers (append-only); each DAQ emission is a chunk
        self.buffers = [np.array([]) for _ in range(16)]
        self.sample_rate = 500

        # connect DAQ signal
        self.daq.data_received.connect(self.on_data)

        # GUI refresh timer
        self.gui_timer = QTimer()
        self.gui_timer.timeout.connect(self.refresh_plot)
        self.gui_timer.start(50)

    def on_data(self, aux_array):
        # aux_array expected shape (16, N)
        for i in range(16):
            self.buffers[i] = np.append(self.buffers[i], aux_array[i, :])
            max_samples = 30000
            if len(self.buffers[i]) > max_samples:
                self.buffers[i] = self.buffers[i][-max_samples:]

    def refresh_plot(self):
        selected = [i for i, cb in enumerate(self.checkboxes) if cb.isChecked()]
        if not selected:
            return
        tlen = max(len(self.buffers[i]) for i in selected)
        if tlen == 0:
            return

        for i in range(16):
            visible = i in selected
            self.curves[i].setVisible(visible)
            if visible and len(self.buffers[i]) > 0:
                data = self.buffers[i]
                data = data - self.offsets.get(i, 0.0)
                x = np.arange(len(data)) / self.sample_rate
                self.curves[i].setData(x, data)

    def remove_offset(self):
        selected = [i for i, cb in enumerate(self.checkboxes) if cb.isChecked()]
        if not selected:
            self.status_label.setText("No channels selected")
            return

        nsamp = int(0.5 * self.sample_rate)
        for i in selected:
            buf = self.buffers[i]
            if len(buf) < nsamp:
                # not enough data yet: take what is available
                if len(buf) == 0:
                    self.offsets[i] = 0.0
                else:
                    self.offsets[i] = float(np.mean(buf))
            else:
                segment = buf[-nsamp:]
                self.offsets[i] = float(np.mean(segment))

        self.status_label.setText("Offsets removed for selected channels")

    def collect_mvc(self):
        selected = [i for i, cb in enumerate(self.checkboxes) if cb.isChecked()]
        if not selected:
            self.status_label.setText("No channels selected for MVC collection")
            return

        duration = 2.0
        nsamp = int(duration * self.sample_rate)

        # ensure enough buffered data; if not, notify and return
        available = min(len(self.buffers[i]) for i in selected)
        if available < nsamp:
            self.status_label.setText(
                "Not enough buffered data yet; wait briefly and try again"
            )
            return

        mvcs = {}
        for i in selected:
            data = self.buffers[i][-nsamp:]
            data = data - self.offsets.get(i, 0.0)
            mvcs[i] = float(np.max(np.abs(data)))

        self.mvc_values = mvcs
        self.status_label.setText(f"MVC collected for channels: {list(mvcs.keys())}")

        # emit values and finish
        self.mvc_collected.emit(mvcs)
        self.finished.emit(selected, self.offsets)
        self.close()
