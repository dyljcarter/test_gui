# Updated MVC Plotter GUI with start and end delays, refined styling, and clear comments

import sys
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


# EntryBox handles input of a single point (time, %MVC)
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Experiment 1 Force GUI")
        self.setGeometry(100, 100, 1200, 700)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout()
        main_widget.setLayout(main_layout)

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
            """
        )

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

        # Animation variables
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)
        self.current_time = 0
        self.time_window = 10
        self.is_animating = False
        self.points = []

        self.entry_boxes = []
        predefined_points = [(5, 0), (10, 30), (20, 30), (25, 0)]
        for i, vals in enumerate(predefined_points):
            entry_box = EntryBox(len(self.entry_boxes), self)
            self.entry_boxes.append(entry_box)
            self.entries_layout.addWidget(entry_box)
            entry_box.time_entry.setText(str(vals[0]))
            entry_box.mvc_entry.setText(str(vals[1]))
        self.update_plot()

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

        self.plot_widget.clear()

        if points:
            times = [p[0] for p in points]
            mvcs = [p[1] for p in points]

            self.plot_widget.plot(
                times, mvcs, pen=pg.mkPen(color=(0, 150, 255), width=5)
            )

            if not self.is_animating:
                self.plot_widget.enableAutoRange()

    # Start animation with initial pause before scrolling
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

        self.start_delay = 1.5  # seconds pause before movement
        self.end_delay = 1.5  # seconds pause after trial before reset
        self.time_step = 0.05
        self.animation_timer.start(50)

    # Update animation frame: handles start delay, scrolling, and end delay
    def update_animation(self):
        if not self.is_animating:
            return

        if self.start_delay > 0:
            self.start_delay -= self.time_step
            return

        self.current_time += self.time_step

        if self.current_time >= self.max_time:
            # Pause at end for end_delay, then stop animation
            self.animation_timer.stop()
            QTimer.singleShot(int(self.end_delay * 1000), self.stop_animation)
            return

        x_start = self.current_time - self.time_window / 2
        x_end = self.current_time + self.time_window / 2
        self.plot_widget.setXRange(x_start, x_end, padding=0)

    # Stop animation and restore auto-ranging
    def stop_animation(self):
        self.is_animating = False
        self.animation_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.plot_widget.enableAutoRange()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
