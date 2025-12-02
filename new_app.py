import sys
import socket
import numpy as np
import threading
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
)
from PyQt5.QtCore import Qt, QTimer
import pyqtgraph as pg


# ============================================================================
# NOVECENTO CONFIGURATION AND HELPER FUNCTIONS
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


# Novecento Configuration
PlotTime = 1
Update_time = 50  # Faster update for real-time plotting
offset = 2

IN_Active = [0] * 10
Mode = [0] * 10
Gain = [0] * 10
HRES = [0] * 10
HPF = [0] * 10
Fsamp = [0] * 10
NumChan = [0] * 10
Ptr_IN = [0] * 11
Size_IN = [0] * 11

ChVsType = [0, 14, 22, 38, 46, 70, 102, 0, 0, 0, 0, 0, 0, 0, 0, 0]

# Configure active inputs (matching your original script)
IN_Active[0] = 1
Mode[0] = 0
Gain[0] = 0
HRES[0] = 0
HPF[0] = 1
Fsamp[0] = 1

IN_Active[1] = 1
Mode[1] = 0
Gain[1] = 0
HRES[1] = 0
HPF[1] = 1
Fsamp[1] = 1

IN_Active[2] = 1
Mode[2] = 0
Gain[2] = 0
HRES[2] = 0
HPF[2] = 1
Fsamp[2] = 1

# Rest are inactive
for i in range(3, 10):
    IN_Active[i] = 0
    Mode[i] = 0
    Gain[i] = 0
    HRES[i] = 0
    HPF[i] = 1
    Fsamp[i] = 1 if i < 8 else 0

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


# ============================================================================
# ENTRY BOX FOR POINTS
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
# MAIN WINDOW WITH NOVECENTO INTEGRATION
# ============================================================================


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Novecento Force Tracking GUI")
        self.setGeometry(100, 100, 1200, 700)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout()
        main_widget.setLayout(main_layout)

        # Novecento connection variables
        self.tcp_socket = None
        self.data_thread = None
        self.terminate_thread = threading.Event()
        self.Data = None
        self.Temp = None
        self.PacketSize1Block = 0
        self.blockData = 0
        self.aux_baseline = None  # For offset removal
        self.realtime_data_buffer = []  # Store real-time data points
        self.realtime_time_buffer = []  # Store corresponding times
        self.experiment_start_time = 0  # Track when experiment starts

        # Left panel setup
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
            QLabel { color: white; }
            """
        )

        # Connection status
        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setStyleSheet(
            "color: #ff6b6b; font-weight: bold; padding: 10px;"
        )
        left_panel_layout.addWidget(self.status_label)

        # Connect button
        self.connect_btn = QPushButton("Connect to Novecento")
        self.connect_btn.clicked.connect(self.connect_novecento)
        left_panel_layout.addWidget(self.connect_btn)

        # Scroll area for entry boxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.entries_layout = QVBoxLayout()
        scroll_widget.setLayout(self.entries_layout)
        scroll.setWidget(scroll_widget)
        left_panel_layout.addWidget(scroll)

        # Control buttons
        btn_layout = QVBoxLayout()
        add_btn = QPushButton("Add Point")
        add_btn.clicked.connect(self.add_entry_box)
        btn_layout.addWidget(add_btn)

        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_animation)
        self.start_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_animation)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        left_panel_layout.addLayout(btn_layout)
        main_layout.addWidget(left_panel)

        # Plot setup
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#2b2b2b")
        self.plot_widget.setLabel(
            "left", "% MVC", **{"color": "#FFFFFF", "font-size": "12pt"}
        )
        self.plot_widget.setLabel(
            "bottom", "Time (s)", **{"color": "#FFFFFF", "font-size": "12pt"}
        )
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        main_layout.addWidget(self.plot_widget)

        # Initialize plot curves
        self.target_curve = None
        self.realtime_curves = []  # Multiple aux channels

        # Animation variables
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)
        self.current_time = 0
        self.time_window = 10
        self.is_animating = False
        self.points = []

        # Data update timer
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.update_realtime_data)

        # Initialize entry boxes with predefined points
        self.entry_boxes = []
        predefined_points = [(5, 0), (10, 30), (20, 30), (25, 0)]
        for i, vals in enumerate(predefined_points):
            entry_box = EntryBox(len(self.entry_boxes), self)
            self.entry_boxes.append(entry_box)
            self.entries_layout.addWidget(entry_box)
            entry_box.time_entry.setText(str(vals[0]))
            entry_box.mvc_entry.setText(str(vals[1]))
        self.update_plot()

    # ========================================================================
    # NOVECENTO CONNECTION METHODS
    # ========================================================================

    def connect_novecento(self):
        try:
            # Connect to socket
            self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.connect(("169.254.1.10", TCPPort))
            print("Connected to the Socket")

            # Request firmware version
            cmd = [2, CRC8([2], 1)]
            self.tcp_socket.sendall(bytearray(cmd))
            firmware_version = self.tcp_socket.recv(20)
            print("Firmware Version:", firmware_version[1:])

            # Request battery level
            cmd = [3, CRC8([3], 1)]
            self.tcp_socket.sendall(bytearray(cmd))
            battery_level = self.tcp_socket.recv(20)
            print("Battery Level: {}%".format(battery_level[1]))

            # Get settings
            cmd = [1, CRC8([1], 1)]
            self.tcp_socket.sendall(bytearray(cmd))
            settings = self.tcp_socket.recv(20)
            if settings[19] == 0:
                print("Error None")
            elif settings[19] == 255:
                print("Error CRC")
            print("Probes configuration:", settings[1:11])

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

            # Send configuration
            self.tcp_socket.sendall(bytearray(ConfString))

            # Re-request settings after configuration (not used but matches original)
            cmd = [1, CRC8([1], 1)]
            self.tcp_socket.sendall(bytearray(cmd))
            settings = self.tcp_socket.recv(20)

            # Calculate packet size
            NumActInputs = 0
            Ptr_IN[0] = 0
            for i in range(10):
                NumChan[i] = ChVsType[settings[i + 1]]
                if NumChan[i] == 0:
                    IN_Active[i] = 0
                if IN_Active[i] == 1:
                    Size_IN[i] = (HRES[i] + 1) * FsampVal[Fsamp[i]] // 500 * NumChan[i]
                    NumActInputs = NumActInputs + 1
                Ptr_IN[i + 1] = Ptr_IN[i] + Size_IN[i]

            self.PacketSize1Block = Ptr_IN[10] + SizeAux[FSelAux] + 128
            self.blockData = self.PacketSize1Block * 500 * PlotTime * 2

            self.tcp_socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF, self.blockData * 2
            )

            # Start data receiving thread
            self.terminate_thread.clear()
            self.data_thread = threading.Thread(target=self.receive_data)
            self.data_thread.start()

            # Start data update timer
            self.data_timer.start(Update_time)

            # Update UI
            self.status_label.setText("Status: Connected")
            self.status_label.setStyleSheet(
                "color: #51cf66; font-weight: bold; padding: 10px;"
            )
            self.connect_btn.setEnabled(False)
            self.start_btn.setEnabled(True)

        except Exception as e:
            print(f"Connection error: {e}")
            self.status_label.setText(f"Status: Error - {str(e)}")
            self.status_label.setStyleSheet(
                "color: #ff6b6b; font-weight: bold; padding: 10px;"
            )

    def receive_data(self):
        """Background thread to receive data from Novecento"""
        buffer = b""
        while not self.terminate_thread.is_set():
            try:
                chunk = self.tcp_socket.recv(self.blockData)
                buffer += chunk
                while len(buffer) >= self.blockData:
                    packet = buffer[: self.blockData]
                    buffer = buffer[self.blockData :]
                    self.Temp = np.frombuffer(packet, dtype="<i2")
                    if len(self.Temp) == self.PacketSize1Block * 500:
                        self.Data = self.Temp.reshape(
                            self.PacketSize1Block, 500, order="F"
                        )
            except (OSError, ValueError) as e:
                if not self.terminate_thread.is_set():
                    print(f"Error receiving data: {e}")
                break

    def update_realtime_data(self):
        """Extract and store real-time aux channel data"""
        if self.Data is None or not self.is_animating:
            return

        try:
            # Extract AUX channels
            Temp = self.Data[Ptr_IN[10] : -128, :].reshape(
                1, 16 * FsampVal[FSelAux] * PlotTime, order="F"
            )
            Sig_AUX = Temp.reshape(16, FsampVal[FSelAux] * PlotTime, order="F").astype(
                np.int32
            )

            # Apply gain and convert to meaningful units
            aux_data = Sig_AUX * AuxGainFactor

            # Remove baseline offset (use first sample as baseline if not set)
            if self.aux_baseline is None:
                self.aux_baseline = np.mean(aux_data[:, :50], axis=1, keepdims=True)

            aux_data_zeroed = aux_data - self.aux_baseline

            # Get current mean value for each channel
            current_values = np.mean(aux_data_zeroed, axis=1)

            # Calculate elapsed time since experiment start
            elapsed_time = self.current_time

            # Store the data points
            self.realtime_data_buffer.append(current_values)
            self.realtime_time_buffer.append(elapsed_time)

            # Keep buffer manageable (last 10000 points)
            if len(self.realtime_data_buffer) > 10000:
                self.realtime_data_buffer.pop(0)
                self.realtime_time_buffer.pop(0)

        except Exception as e:
            print(f"Error processing real-time data: {e}")

    # ========================================================================
    # GUI CONTROL METHODS
    # ========================================================================

    def add_entry_box(self):
        entry_box = EntryBox(len(self.entry_boxes), self)
        self.entry_boxes.append(entry_box)
        self.entries_layout.addWidget(entry_box)
        self.update_plot()

    def update_plot(self):
        """Update the target trajectory plot"""
        points = []
        for entry_box in self.entry_boxes:
            values = entry_box.get_values()
            if values:
                points.append(values)

        points.sort(key=lambda x: x[0])
        self.points = points

        self.plot_widget.clear()
        self.target_curve = None
        self.realtime_curves = []

        if points:
            times = [p[0] for p in points]
            mvcs = [p[1] for p in points]

            # Plot target trajectory
            self.target_curve = self.plot_widget.plot(
                times, mvcs, pen=pg.mkPen(color=(0, 150, 255), width=5), name="Target"
            )

            # Initialize real-time data curves (16 aux channels)
            colors = [
                (255, 100, 100),
                (100, 255, 100),
                (255, 255, 100),
                (255, 100, 255),
                (100, 255, 255),
                (255, 200, 100),
                (200, 100, 255),
                (100, 255, 200),
                (255, 150, 150),
                (150, 255, 150),
                (255, 255, 150),
                (255, 150, 255),
                (150, 255, 255),
                (255, 200, 150),
                (200, 150, 255),
                (150, 255, 200),
            ]
            for i in range(16):
                curve = self.plot_widget.plot(
                    [], [], pen=pg.mkPen(color=colors[i], width=2), name=f"AUX {i+1}"
                )
                self.realtime_curves.append(curve)

            if not self.is_animating:
                self.plot_widget.enableAutoRange()

    def start_animation(self):
        if not self.points:
            return

        self.is_animating = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # Reset baseline and buffers
        self.aux_baseline = None
        self.realtime_data_buffer = []
        self.realtime_time_buffer = []

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
        self.experiment_start_time = self.current_time

        x_start = self.current_time - self.time_window / 2
        x_end = self.current_time + self.time_window / 2
        self.plot_widget.setXRange(x_start, x_end, padding=0)

        self.start_delay = 1.5
        self.end_delay = 1.5
        self.time_step = 0.05
        self.animation_timer.start(50)

    def update_animation(self):
        """Update animation frame and overlay real-time data"""
        if not self.is_animating:
            return

        # Handle start delay
        if self.start_delay > 0:
            self.start_delay -= self.time_step
            return

        self.current_time += self.time_step

        # Update real-time data plots
        if len(self.realtime_data_buffer) > 0:
            data_array = np.array(self.realtime_data_buffer)
            time_array = np.array(self.realtime_time_buffer)

            for i, curve in enumerate(self.realtime_curves):
                if i < data_array.shape[1]:
                    curve.setData(time_array, data_array[:, i])

        # Check if animation should end
        if self.current_time >= self.max_time:
            self.animation_timer.stop()
            QTimer.singleShot(int(self.end_delay * 1000), self.stop_animation)
            return

        # Update view window
        x_start = self.current_time - self.time_window / 2
        x_end = self.current_time + self.time_window / 2
        self.plot_widget.setXRange(x_start, x_end, padding=0)

    def stop_animation(self):
        self.is_animating = False
        self.animation_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.plot_widget.enableAutoRange()

    def closeEvent(self, event):
        """Clean up when closing the application"""
        if self.tcp_socket:
            self.terminate_thread.set()
            self.data_timer.stop()
            self.animation_timer.stop()

            # Stop data transfer
            ConfString = [0] * 15
            ConfString[0] = int("00000000", 2)
            ConfString[14] = CRC8(ConfString, 14)
            try:
                self.tcp_socket.sendall(bytearray(ConfString))
                self.tcp_socket.close()
            except:
                pass

            if self.data_thread:
                self.data_thread.join(timeout=2)

            print("Socket closed")

        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
