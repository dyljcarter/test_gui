import sys
import socket
import numpy as np
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QCheckBox,
    QGroupBox,
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
import pyqtgraph as pg
import threading


# ============================================================================
# DAQ Communication Functions (from read_novecento.py)
# ============================================================================


def CRC8(Vector, Len):
    crc = 0
    j = 0

    while Len > 0:
        Extract = Vector[j]
        for i in range(8, 0, -1):
            Sum = crc % 2 ^ Extract % 2
            crc //= 2

            if Sum > 0:
                a = format(crc, "08b")
                b = format(140, "08b")
                str_list = [0] * 8

                for k in range(8):
                    str_list[k] = int(a[k] != b[k])

                crc = int("".join(map(str, str_list)), 2)

            Extract //= 2

        Len -= 1
        j += 1

    return crc


# ============================================================================
# DAQ Data Receiver Thread
# ============================================================================


class DAQReceiver(QThread):
    data_received = pyqtSignal(np.ndarray)

    def __init__(self, daq_config):
        super().__init__()
        self.daq_config = daq_config
        self.running = False
        self.tcp_socket = None

    def run(self):
        self.running = True
        self.connect_daq()
        buffer = b""

        while self.running:
            try:
                chunk = self.tcp_socket.recv(self.daq_config["blockData"])
                buffer += chunk

                while len(buffer) >= self.daq_config["blockData"]:
                    packet = buffer[: self.daq_config["blockData"]]
                    buffer = buffer[self.daq_config["blockData"] :]

                    Temp = np.frombuffer(packet, dtype="<i2")
                    if len(Temp) == self.daq_config["PacketSize1Block"] * 500:
                        Data = Temp.reshape(
                            self.daq_config["PacketSize1Block"], 500, order="F"
                        )
                        # Extract AUX channels
                        Temp_aux = Data[
                            self.daq_config["Ptr_IN"][10] : -128, :
                        ].reshape(
                            1,
                            16
                            * self.daq_config["FsampVal"][self.daq_config["FSelAux"]]
                            * self.daq_config["PlotTime"],
                            order="F",
                        )
                        Sig_AUX = Temp_aux.reshape(
                            16,
                            self.daq_config["FsampVal"][self.daq_config["FSelAux"]]
                            * self.daq_config["PlotTime"],
                            order="F",
                        ).astype(np.int32)

                        # Convert to physical units
                        Sig_AUX_scaled = Sig_AUX * self.daq_config["AuxGainFactor"]
                        self.data_received.emit(Sig_AUX_scaled)

            except Exception as e:
                print(f"Error receiving data: {e}")
                break

    def connect_daq(self):
        # DAQ Configuration
        PlotTime = 1
        offset = 2

        IN_Active = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
        Mode = [0] * 10
        Gain = [0] * 10
        HRES = [0] * 10
        HPF = [1] * 10
        Fsamp = [1] * 8 + [0, 0]

        ChVsType = [0, 14, 22, 38, 46, 70, 102, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        AuxFsamp = [0, 16, 32, 48]
        FsampVal = [500, 2000, 4000, 8000]
        SizeAux = [16, 64, 128, 256]
        FSelAux = 0

        AnOutINSource = 2
        AnOutChan = 1
        AnOutGain = int("00100000", 2)

        TCPPort = 23456
        GainFactor = 0.0002861
        AuxGainFactor = 5 / 2**16 / 0.5

        # Build configuration string
        ConfString = [0] * 15
        ConfString[0] = (
            int("10000000", 2) + AuxFsamp[FSelAux] + IN_Active[9] * 2 + IN_Active[8]
        )
        ConfString[1] = 0
        for i in range(8):
            ConfString[1] += IN_Active[i] * (2**i)
        ConfString[2] = AnOutGain + AnOutINSource
        ConfString[3] = AnOutChan
        for i in range(10):
            ConfString[4 + i] = (
                Mode[i] * 64 + Gain[i] * 16 + HPF[i] * 8 + HRES[i] * 4 + Fsamp[i]
            )
        ConfString[14] = CRC8(ConfString, 14)

        # Connect to DAQ
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.connect(("169.254.1.10", TCPPort))
        print("Connected to DAQ")

        # Send configuration
        self.tcp_socket.sendall(bytearray(ConfString))

        # Calculate packet parameters
        NumChan = [0] * 10
        Ptr_IN = [0] * 11
        Size_IN = [0] * 11

        settings = self.send_request(1)

        for i in range(10):
            NumChan[i] = ChVsType[settings[i + 1]]
            if NumChan[i] == 0:
                IN_Active[i] = 0
            if IN_Active[i] == 1:
                Size_IN[i] = (HRES[i] + 1) * FsampVal[Fsamp[i]] // 500 * NumChan[i]
            Ptr_IN[i + 1] = Ptr_IN[i] + Size_IN[i]

        PacketSize1Block = Ptr_IN[10] + SizeAux[FSelAux] + 128
        blockData = PacketSize1Block * 500 * PlotTime * 2

        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, blockData * 2)

        # Store config for data processing
        self.daq_config["PlotTime"] = PlotTime
        self.daq_config["Ptr_IN"] = Ptr_IN
        self.daq_config["PacketSize1Block"] = PacketSize1Block
        self.daq_config["blockData"] = blockData
        self.daq_config["FSelAux"] = FSelAux
        self.daq_config["FsampVal"] = FsampVal
        self.daq_config["AuxGainFactor"] = AuxGainFactor

    def send_request(self, command):
        cmd = [command, CRC8([command], 1)]
        self.tcp_socket.sendall(bytearray(cmd))
        response = self.tcp_socket.recv(20)
        return response

    def stop(self):
        self.running = False
        if self.tcp_socket:
            # Stop data transfer
            ConfString = [0] * 15
            ConfString[0] = int("00000000", 2)
            ConfString[14] = CRC8(ConfString, 14)
            self.tcp_socket.sendall(bytearray(ConfString))
            self.tcp_socket.close()
            print("DAQ connection closed")


# ============================================================================
# Entry Box Widget
# ============================================================================


class EntryBox(QWidget):
    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.parent_window = parent

        self.setStyleSheet(
            """
            QWidget { background-color: #3a3a3a; border-radius: 6px; padding: 8px; }
            QLabel { color: white; font-weight: bold; }
            QLineEdit { background-color: #2b2b2b; border: 1px solid #555; border-radius: 4px; padding: 5px; font-size: 11pt; color: white; }
            QLineEdit:focus { border: 1px solid #4a90e2; }
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel(f"Point {index + 1}")
        layout.addWidget(header)

        row = QHBoxLayout()
        row.addWidget(QLabel("% MVC:"))
        self.mvc_entry = QLineEdit()
        self.mvc_entry.setPlaceholderText("0-100")
        self.mvc_entry.setMaximumWidth(80)
        self.mvc_entry.textChanged.connect(self.on_value_changed)
        row.addWidget(self.mvc_entry)

        row.addWidget(QLabel("Time (s):"))
        self.time_entry = QLineEdit()
        self.time_entry.setPlaceholderText("seconds")
        self.time_entry.setMaximumWidth(80)
        self.time_entry.textChanged.connect(self.on_value_changed)
        row.addWidget(self.time_entry)

        layout.addLayout(row)
        self.setLayout(layout)

    def on_value_changed(self):
        if self.parent_window:
            self.parent_window.update_plot()

    def get_values(self):
        try:
            mvc = float(self.mvc_entry.text())
            time = float(self.time_entry.text())
            return (time, mvc)
        except ValueError:
            return None


# ============================================================================
# Main Window
# ============================================================================


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DAQ + Force Protocol GUI")
        self.setGeometry(100, 100, 1400, 700)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout()
        main_widget.setLayout(main_layout)

        # ====================================================================
        # Left Panel: Protocol Configuration
        # ====================================================================
        left_panel = QWidget()
        left_panel_layout = QVBoxLayout()
        left_panel.setLayout(left_panel_layout)
        left_panel.setMaximumWidth(320)
        left_panel.setStyleSheet(
            """
            QWidget { background-color: #202020; }
            QPushButton { background-color: #4a90e2; color: white; border: none; border-radius: 6px; padding: 10px; font-size: 12pt; margin-top: 6px; }
            QPushButton:hover { background-color: #357abd; }
            QPushButton:pressed { background-color: #2a5d91; }
            QPushButton:disabled { background-color: #555; color: #999; }
            """
        )

        # Protocol points
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.entries_layout = QVBoxLayout()
        scroll_widget.setLayout(self.entries_layout)
        scroll.setWidget(scroll_widget)
        left_panel_layout.addWidget(scroll)

        # Buttons
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

        # ====================================================================
        # Center: Plot
        # ====================================================================
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

        # ====================================================================
        # Right Panel: AUX Channel Selection
        # ====================================================================
        right_panel = QWidget()
        right_panel_layout = QVBoxLayout()
        right_panel.setLayout(right_panel_layout)
        right_panel.setMaximumWidth(250)
        right_panel.setStyleSheet(
            """
            QWidget { background-color: #202020; }
            QGroupBox { color: white; font-weight: bold; border: 1px solid #555; border-radius: 6px; margin-top: 10px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QCheckBox { color: white; padding: 4px; }
            QCheckBox::indicator { width: 18px; height: 18px; }
            """
        )

        # DAQ Control
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

        # Channel selection
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
            self.channel_checkboxes.append(cb)
            self.channel_layout.addWidget(cb)

        # Enable first channel by default
        self.channel_checkboxes[0].setChecked(True)

        channel_group_layout = QVBoxLayout()
        channel_group_layout.addWidget(channel_scroll)
        channel_group.setLayout(channel_group_layout)
        right_panel_layout.addWidget(channel_group)

        right_panel_layout.addStretch()
        main_layout.addWidget(right_panel)

        # ====================================================================
        # Initialize Variables
        # ====================================================================
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)
        self.current_time = 0
        self.time_window = 10
        self.is_animating = False
        self.points = []
        self.entry_boxes = []

        # DAQ variables
        self.daq_receiver = None
        self.aux_data = [np.array([]) for _ in range(16)]  # Store data for each channel
        self.aux_curves = []  # Plot curves for AUX channels
        self.protocol_curve = None  # Curve for protocol trace

        # Create curves for AUX channels (initially hidden)
        colors = [pg.intColor(i, 16) for i in range(16)]
        for i in range(16):
            curve = self.plot_widget.plot(
                [], [], pen=pg.mkPen(color=colors[i], width=2), name=f"AUX {i}"
            )
            curve.setVisible(False)
            self.aux_curves.append(curve)

        # Initialize with predefined protocol points
        predefined_points = [(5, 0), (10, 30), (20, 30), (25, 0)]
        for i, vals in enumerate(predefined_points):
            entry_box = EntryBox(len(self.entry_boxes), self)
            self.entry_boxes.append(entry_box)
            self.entries_layout.addWidget(entry_box)
            entry_box.time_entry.setText(str(vals[0]))
            entry_box.mvc_entry.setText(str(vals[1]))

        self.update_plot()

    # ========================================================================
    # DAQ Functions
    # ========================================================================

    def connect_daq(self):
        try:
            self.daq_receiver = DAQReceiver({"blockData": 0})
            self.daq_receiver.data_received.connect(self.update_aux_data)
            self.daq_receiver.start()

            self.connect_daq_btn.setEnabled(False)
            self.disconnect_daq_btn.setEnabled(True)
            print("DAQ connected successfully")
        except Exception as e:
            print(f"Failed to connect to DAQ: {e}")

    def disconnect_daq(self):
        if self.daq_receiver:
            self.daq_receiver.stop()
            self.daq_receiver.wait()
            self.daq_receiver = None

            self.connect_daq_btn.setEnabled(True)
            self.disconnect_daq_btn.setEnabled(False)
            print("DAQ disconnected")

    def update_aux_data(self, aux_signals):
        """Receive new AUX data from DAQ and update plots"""
        for i in range(16):
            # Append new data to existing buffer
            self.aux_data[i] = np.append(self.aux_data[i], aux_signals[i, :])

            # Keep only recent data (e.g., last 60 seconds at 500 Hz)
            max_samples = 30000  # 60 seconds at 500 Hz
            if len(self.aux_data[i]) > max_samples:
                self.aux_data[i] = self.aux_data[i][-max_samples:]

        self.update_aux_plots()

    def update_aux_plots(self):
        """Update the AUX channel plots"""
        if not any(cb.isChecked() for cb in self.channel_checkboxes):
            return

        # Calculate time axis based on sampling rate (500 Hz from config)
        sample_rate = 500  # Hz

        for i in range(16):
            if self.channel_checkboxes[i].isChecked() and len(self.aux_data[i]) > 0:
                time_axis = np.arange(len(self.aux_data[i])) / sample_rate
                # Offset to align with current animation time if animating
                if self.is_animating:
                    time_axis = time_axis + (
                        self.current_time - len(self.aux_data[i]) / sample_rate
                    )
                self.aux_curves[i].setData(time_axis, self.aux_data[i])

    def update_channel_visibility(self):
        """Show/hide AUX channel curves based on checkboxes"""
        for i, cb in enumerate(self.channel_checkboxes):
            self.aux_curves[i].setVisible(cb.isChecked())

    # ========================================================================
    # Protocol Functions
    # ========================================================================

    def add_entry_box(self):
        entry_box = EntryBox(len(self.entry_boxes), self)
        self.entry_boxes.append(entry_box)
        self.entries_layout.addWidget(entry_box)
        self.update_plot()

    def update_plot(self):
        points = []
        for entry_box in self.entry_boxes:
            values = entry_box.get_values()
            if values:
                points.append(values)

        points.sort(key=lambda x: x[0])
        self.points = points

        # Clear only the protocol curve, not AUX curves
        if self.protocol_curve:
            self.plot_widget.removeItem(self.protocol_curve)

        if points:
            times = [p[0] for p in points]
            mvcs = [p[1] for p in points]

            self.protocol_curve = self.plot_widget.plot(
                times,
                mvcs,
                pen=pg.mkPen(color=(255, 200, 0), width=3, style=Qt.DashLine),
                name="Protocol",
            )

            if not self.is_animating:
                self.plot_widget.enableAutoRange()

    def start_animation(self):
        if not self.points:
            return

        self.is_animating = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        mvcs = [p[1] for p in self.points]
        max_mvc = max(mvcs)
        min_mvc = min(0, min(mvcs))
        self.plot_widget.setYRange(min_mvc - 5, max_mvc + 10, padding=0)

        times = [p[0] for p in self.points]
        self.min_time = min(times)
        self.max_time = max(times)

        padding = self.time_window / 2
        self.display_min = self.min_time - padding
        self.display_max = self.max_time + padding

        self.current_time = self.min_time
        x_start = self.current_time - self.time_window / 2
        x_end = self.current_time + self.time_window / 2
        self.plot_widget.setXRange(x_start, x_end, padding=0)

        self.start_delay = 1.5
        self.end_delay = 1.5
        self.time_step = 0.05
        self.animation_timer.start(50)

        # Clear old AUX data when starting new trial
        for i in range(16):
            self.aux_data[i] = np.array([])

    def update_animation(self):
        if not self.is_animating:
            return

        if self.start_delay > 0:
            self.start_delay -= self.time_step
            return

        self.current_time += self.time_step

        if self.current_time >= self.max_time:
            self.animation_timer.stop()
            QTimer.singleShot(int(self.end_delay * 1000), self.stop_animation)
            return

        x_start = self.current_time - self.time_window / 2
        x_end = self.current_time + self.time_window / 2
        self.plot_widget.setXRange(x_start, x_end, padding=0)

        # Update AUX plots during animation
        self.update_aux_plots()

    def stop_animation(self):
        self.is_animating = False
        self.animation_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.plot_widget.enableAutoRange()

    def closeEvent(self, event):
        """Clean up when closing the window"""
        if self.daq_receiver:
            self.disconnect_daq()
        event.accept()


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
