import socket
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


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


class DAQReceiver(QThread):
    """
    Threaded DAQ receiver that emits aux channel data as a 2D numpy array
    with shape (16, N_samples). Signals:
      - data_received(np.ndarray)
      - connected()
      - disconnected()
      - error(str)
    """

    data_received = pyqtSignal(np.ndarray)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, host="169.254.1.10", port=23456, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.running = False
        self.tcp_socket = None
        self.daq_config = {}

    def run(self):
        try:
            self.running = True
            self.connect_daq()
            buffer = b""

            while self.running:
                # Receive chunk (blocking)
                chunk = self.tcp_socket.recv(self.daq_config["blockData"])
                if not chunk:
                    break
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

                        Sig_AUX_scaled = Sig_AUX * self.daq_config["AuxGainFactor"]
                        # Emit shape (16, N)
                        self.data_received.emit(Sig_AUX_scaled)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.disconnect()

    def connect_daq(self):
        # Configuration (taken from original script)
        PlotTime = 1
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

        TCPPort = self.port
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
        self.tcp_socket.connect((self.host, TCPPort))
        # Give a reasonably large receive buffer
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024 * 8)
        self.tcp_socket.sendall(bytearray(ConfString))

        # Calculate packet parameters
        NumChan = [0] * 10
        Ptr_IN = [0] * 11
        Size_IN = [0] * 11

        # Query settings
        settings = self.send_request(1)
        # settings is raw bytes; keep safe indexing
        if isinstance(settings, (bytes, bytearray)) and len(settings) >= 11:
            settings_arr = settings
        else:
            settings_arr = [0] * 11

        for i in range(10):
            idx = settings_arr[i + 1] if i + 1 < len(settings_arr) else 0
            NumChan[i] = ChVsType[idx] if idx < len(ChVsType) else 0
            if NumChan[i] == 0:
                IN_Active[i] = 0
            if IN_Active[i] == 1:
                Size_IN[i] = (HRES[i] + 1) * FsampVal[Fsamp[i]] // 500 * NumChan[i]
            Ptr_IN[i + 1] = Ptr_IN[i] + Size_IN[i]

        PacketSize1Block = Ptr_IN[10] + SizeAux[FSelAux] + 128
        blockData = PacketSize1Block * 500 * PlotTime * 2

        # Store config
        self.daq_config.update(
            {
                "PlotTime": PlotTime,
                "Ptr_IN": Ptr_IN,
                "PacketSize1Block": PacketSize1Block,
                "blockData": blockData,
                "FSelAux": FSelAux,
                "FsampVal": FsampVal,
                "AuxGainFactor": AuxGainFactor,
            }
        )
        self.connected.emit()

    def send_request(self, command):
        cmd = [command, CRC8([command], 1)]
        try:
            self.tcp_socket.sendall(bytearray(cmd))
            response = self.tcp_socket.recv(20)
            return response
        except Exception:
            return bytearray([0] * 20)

    def stop(self):
        self.running = False

    def disconnect(self):
        try:
            if self.tcp_socket:
                ConfString = [0] * 15
                ConfString[0] = int("00000000", 2)
                ConfString[14] = CRC8(ConfString, 14)
                try:
                    self.tcp_socket.sendall(bytearray(ConfString))
                except Exception:
                    pass
                try:
                    self.tcp_socket.close()
                except Exception:
                    pass
        finally:
            self.disconnected.emit()
