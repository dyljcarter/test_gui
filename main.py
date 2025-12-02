import sys
from PyQt5.QtWidgets import QApplication
from utils.daq_receiver import DAQReceiver
from utils.mvc_window import MVCWindow
from utils.protocol_window import ProtocolWindow


def main():
    app = QApplication(sys.argv)

    # Instantiate DAQ receiver (not started yet)
    daq = DAQReceiver()

    mvc_win = MVCWindow(daq)

    # When MVCWindow finishes it emits selected channels and offsets.
    def on_finished(selected_channels, offsets):
        # Query mvc_values from mvc_win (already set at collection)
        mvc_values = mvc_win.mvc_values if hasattr(mvc_win, "mvc_values") else {}
        prot = ProtocolWindow(daq, selected_channels, mvc_values, offsets)
        prot.show()

    mvc_win.finished.connect(on_finished)
    mvc_win.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
