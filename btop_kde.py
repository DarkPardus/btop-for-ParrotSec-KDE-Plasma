#!/usr/bin/env python3
"""btop-kde: btop benzeri sistem izleyici, KDE Plasma (Breeze) uyumlu.

Gereksinimler:  pip install --user PySide6 psutil
Calistirma:     python3 btop_kde.py
Menuye ekleme:  python3 btop_kde.py --install
"""
import os
import signal
import stat
import sys
from collections import deque

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# Breeze renkleri
BLUE, GREEN, ORANGE, RED, PURPLE = "#3daee9", "#27ae60", "#f67400", "#da4453", "#9b59b6"
HISTORY = 120
INTERVAL_MS = 1000
PROC_EVERY = 2  # surec tablosu kac tikte bir yenilensin

APP_NAME = "btop-kde"


def human(n, suffix="B"):
    for unit in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}{suffix}" if unit else f"{n:.0f} {suffix}"
        n /= 1024
    return f"{n:.1f} P{suffix}"


def lerp_color(c1, c2, t):
    a, b = QColor(c1), QColor(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


class Graph(QWidget):
    """Alan grafigi. maximum=None ise otomatik olceklenir."""

    def __init__(self, color=BLUE, maximum=100.0, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.maximum = maximum
        self.data = deque([0.0] * HISTORY, maxlen=HISTORY)
        self.setMinimumHeight(70)

    def push(self, value):
        self.data.append(value)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        grid = QColor(self.palette().color(self.foregroundRole()))
        grid.setAlpha(35)
        p.setPen(QPen(grid, 1))
        for i in range(1, 4):
            y = h * i / 4
            p.drawLine(0, int(y), w, int(y))

        top = self.maximum if self.maximum else max(max(self.data), 1.0) * 1.15
        step = w / (HISTORY - 1)
        pts = [QPointF(i * step, h - min(v / top, 1.0) * (h - 2) - 1)
               for i, v in enumerate(self.data)]

        fill = QPainterPath()
        fill.moveTo(0, h)
        for pt in pts:
            fill.lineTo(pt)
        fill.lineTo(w, h)
        fill.closeSubpath()
        c = QColor(self.color)
        c.setAlpha(70)
        p.fillPath(fill, c)

        p.setPen(QPen(self.color, 1.8))
        p.drawPolyline(QPolygonF(pts))
        p.end()


class Box(QFrame):
    """btop tarzi basikli kutu."""

    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.color = color
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(f"Box {{ border: 1px solid {color}; border-radius: 4px; }}")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(8, 6, 8, 8)
        self.title = QLabel(title)
        self.title.setStyleSheet(f"color:{color}; font-weight:bold;")
        self.v.addWidget(self.title)

    def set_title(self, text):
        self.title.setText(text)


def bar(color):
    b = QProgressBar()
    b.setRange(0, 100)
    b.setTextVisible(True)
    b.setFixedHeight(16)
    b.setStyleSheet(
        f"QProgressBar {{ border:none; border-radius:3px; background:rgba(127,127,127,45);"
        f" text-align:center; font-size:10px; }}"
        f"QProgressBar::chunk {{ background:{color}; border-radius:3px; }}"
    )
    return b


def load_color(pct):
    if pct < 50:
        return lerp_color(GREEN, ORANGE, pct / 50).name()
    return lerp_color(ORANGE, RED, (pct - 50) / 50).name()


class NumItem(QTableWidgetItem):
    def __init__(self, value, text):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("btop — Sistem İzleyici")
        self.resize(1100, 760)
        self.tick = 0
        self.prev_net = psutil.net_io_counters()
        self.ncpu = psutil.cpu_count(logical=True)

        central = QWidget()
        self.setCentralWidget(central)
        grid = QGridLayout(central)
        grid.setSpacing(8)
        grid.setContentsMargins(8, 8, 8, 8)

        # --- CPU
        self.cpu_box = Box("CPU", BLUE)
        self.cpu_graph = Graph(BLUE, 100.0)
        self.cpu_box.v.addWidget(self.cpu_graph)
        cores = QGridLayout()
        cores.setSpacing(3)
        self.core_bars = []
        cols = 2 if self.ncpu > 4 else 1
        for i in range(self.ncpu):
            row = QHBoxLayout()
            lbl = QLabel(f"C{i}")
            lbl.setFixedWidth(26)
            b = bar(GREEN)
            row.addWidget(lbl)
            row.addWidget(b)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            cores.addWidget(holder, i // cols, i % cols)
            self.core_bars.append(b)
        self.cpu_box.v.addLayout(cores)
        self.load_lbl = QLabel()
        self.cpu_box.v.addWidget(self.load_lbl)

        # --- Bellek
        self.mem_box = Box("Bellek", GREEN)
        self.mem_graph = Graph(GREEN, 100.0)
        self.mem_box.v.addWidget(self.mem_graph)
        self.mem_bar = bar(GREEN)
        self.swap_bar = bar(PURPLE)
        self.mem_lbl = QLabel()
        self.swap_lbl = QLabel()
        for wdg in (self.mem_lbl, self.mem_bar, self.swap_lbl, self.swap_bar):
            self.mem_box.v.addWidget(wdg)
        self.disk_widgets = {}
        self.disk_layout = QVBoxLayout()
        self.mem_box.v.addLayout(self.disk_layout)
        self.mem_box.v.addStretch(1)

        # --- Ag
        self.net_box = Box("Ağ", PURPLE)
        self.down_graph = Graph(BLUE, None)
        self.up_graph = Graph(ORANGE, None)
        self.down_lbl = QLabel("▼ 0 B/s")
        self.up_lbl = QLabel("▲ 0 B/s")
        self.down_lbl.setStyleSheet(f"color:{BLUE}; font-weight:bold;")
        self.up_lbl.setStyleSheet(f"color:{ORANGE}; font-weight:bold;")
        for wdg in (self.down_lbl, self.down_graph, self.up_lbl, self.up_graph):
            self.net_box.v.addWidget(wdg)
        self.net_total = QLabel()
        self.net_box.v.addWidget(self.net_total)

        # --- Surecler
        self.proc_box = Box("Süreçler", ORANGE)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtre (ad, kullanıcı veya PID)…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["PID", "Ad", "Kullanıcı", "CPU %", "Bel %", "Bellek"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSortIndicatorShown(True)
        hh.sectionClicked.connect(self.on_header)
        self.sort_col, self.sort_order = 3, Qt.DescendingOrder
        hh.setSortIndicator(self.sort_col, self.sort_order)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.menu)
        self.proc_box.v.addWidget(self.filter)
        self.proc_box.v.addWidget(self.table)

        grid.addWidget(self.cpu_box, 0, 0)
        grid.addWidget(self.mem_box, 0, 1)
        grid.addWidget(self.net_box, 0, 2)
        grid.addWidget(self.proc_box, 1, 0, 1, 3)
        grid.setRowStretch(0, 4)
        grid.setRowStretch(1, 5)

        # Sinyaller / kisayollar
        act = QAction(self)
        act.setShortcut("Ctrl+Q")
        act.triggered.connect(self.close)
        self.addAction(act)
        find = QAction(self)
        find.setShortcut("Ctrl+F")
        find.triggered.connect(self.filter.setFocus)
        self.addAction(find)

        # cpu_percent'i isit
        psutil.cpu_percent(percpu=True)
        for p in psutil.process_iter():
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(INTERVAL_MS)
        QTimer.singleShot(300, self.refresh)

    # ---------- yenileme
    def refresh(self):
        self.tick += 1
        per = psutil.cpu_percent(percpu=True)
        total = sum(per) / len(per)
        self.cpu_graph.push(total)
        title = f"CPU  {total:.0f}%"
        try:
            temps = psutil.sensors_temperatures()
            for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal"):
                if key in temps and temps[key]:
                    title += f"   {temps[key][0].current:.0f}°C"
                    break
        except (AttributeError, OSError):
            pass
        try:
            f = psutil.cpu_freq()
            if f:
                title += f"   {f.current / 1000:.2f} GHz"
        except Exception:
            pass
        self.cpu_box.set_title(title)
        for b, v in zip(self.core_bars, per):
            b.setValue(int(v))
            b.setFormat(f"{v:.0f}%")
            b.setStyleSheet(self._chunk_style(v))
        la = os.getloadavg()
        self.load_lbl.setText(f"Yük ort.: {la[0]:.2f}  {la[1]:.2f}  {la[2]:.2f}")

        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        self.mem_graph.push(vm.percent)
        self.mem_box.set_title(f"Bellek  {vm.percent:.0f}%")
        self.mem_lbl.setText(f"RAM: {human(vm.used)} / {human(vm.total)}  (boş: {human(vm.available)})")
        self.mem_bar.setValue(int(vm.percent))
        self.swap_lbl.setText(f"Takas: {human(sw.used)} / {human(sw.total)}")
        self.swap_bar.setValue(int(sw.percent))
        self.update_disks()

        net = psutil.net_io_counters()
        dt = INTERVAL_MS / 1000
        down = (net.bytes_recv - self.prev_net.bytes_recv) / dt
        up = (net.bytes_sent - self.prev_net.bytes_sent) / dt
        self.prev_net = net
        self.down_graph.push(down)
        self.up_graph.push(up)
        self.down_lbl.setText(f"▼ {human(down)}/s")
        self.up_lbl.setText(f"▲ {human(up)}/s")
        self.net_total.setText(f"Toplam: ▼ {human(net.bytes_recv)}  ▲ {human(net.bytes_sent)}")

        if self.tick % PROC_EVERY == 1 or self.tick == 1:
            self.update_procs()

    @staticmethod
    def _chunk_style(v):
        return (
            "QProgressBar { border:none; border-radius:3px; background:rgba(127,127,127,45);"
            " text-align:center; font-size:10px; }"
            f"QProgressBar::chunk {{ background:{load_color(v)}; border-radius:3px; }}"
        )

    def update_disks(self):
        seen = set()
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint in seen or part.fstype in ("squashfs", "tmpfs", "devtmpfs"):
                continue
            if part.mountpoint.startswith(("/snap", "/boot/efi", "/var/lib/docker")):
                continue
            seen.add(part.mountpoint)
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            if part.mountpoint not in self.disk_widgets:
                lbl, b = QLabel(), bar(BLUE)
                self.disk_layout.addWidget(lbl)
                self.disk_layout.addWidget(b)
                self.disk_widgets[part.mountpoint] = (lbl, b)
            lbl, b = self.disk_widgets[part.mountpoint]
            lbl.setText(f"{part.mountpoint}: {human(u.used)} / {human(u.total)}")
            b.setValue(int(u.percent))

    # ---------- surecler
    def on_header(self, col):
        if col == self.sort_col:
            self.sort_order = (Qt.AscendingOrder if self.sort_order == Qt.DescendingOrder
                               else Qt.DescendingOrder)
        else:
            self.sort_col = col
            self.sort_order = Qt.AscendingOrder if col in (1, 2) else Qt.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(self.sort_col, self.sort_order)
        self.table.sortItems(self.sort_col, self.sort_order)

    def selected_pid(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return int(self.table.item(row, 0).text())

    def update_procs(self):
        keep = self.selected_pid()
        rows = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent",
                                      "memory_percent", "memory_info"]):
            i = p.info
            if i["memory_info"] is None:
                continue
            rows.append(i)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, i in enumerate(rows):
            cpu = (i["cpu_percent"] or 0.0) / self.ncpu  # btop gibi toplam cekirdege gore
            mem = i["memory_percent"] or 0.0
            rss = i["memory_info"].rss
            pid_item = NumItem(i["pid"], str(i["pid"]))
            name_item = QTableWidgetItem(i["name"] or "?")
            user_item = QTableWidgetItem(i["username"] or "?")
            cpu_item = NumItem(cpu, f"{cpu:.1f}")
            mem_item = NumItem(mem, f"{mem:.1f}")
            rss_item = NumItem(rss, human(rss))
            if cpu >= 50:
                cpu_item.setForeground(QColor(RED))
            elif cpu >= 15:
                cpu_item.setForeground(QColor(ORANGE))
            for c, it in enumerate((pid_item, name_item, user_item, cpu_item, mem_item, rss_item)):
                self.table.setItem(r, c, it)
        self.table.sortItems(self.sort_col, self.sort_order)
        self.table.setSortingEnabled(False)
        self.apply_filter()
        if keep is not None:
            for r in range(self.table.rowCount()):
                if int(self.table.item(r, 0).text()) == keep:
                    self.table.selectRow(r)
                    break
        self.proc_box.set_title(f"Süreçler  ({len(rows)})")

    def apply_filter(self):
        q = self.filter.text().strip().lower()
        for r in range(self.table.rowCount()):
            if not q:
                self.table.setRowHidden(r, False)
                continue
            text = " ".join(self.table.item(r, c).text().lower() for c in range(3))
            self.table.setRowHidden(r, q not in text)

    def menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        self.table.selectRow(item.row())
        pid = self.selected_pid()
        m = QMenu(self)
        for label, sig in (("Sonlandır (SIGTERM)", signal.SIGTERM),
                           ("Zorla öldür (SIGKILL)", signal.SIGKILL),
                           ("Duraklat (SIGSTOP)", signal.SIGSTOP),
                           ("Devam ettir (SIGCONT)", signal.SIGCONT)):
            a = m.addAction(label)
            a.triggered.connect(lambda _=False, s=sig: self.send(pid, s))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def send(self, pid, sig):
        try:
            name = psutil.Process(pid).name()
            if sig in (signal.SIGTERM, signal.SIGKILL):
                ok = QMessageBox.question(
                    self, "Onay", f"{name} (PID {pid}) sürecine {signal.Signals(sig).name} gönderilsin mi?")
                if ok != QMessageBox.Yes:
                    return
            os.kill(pid, sig)
        except psutil.NoSuchProcess:
            pass
        except PermissionError:
            QMessageBox.warning(self, "İzin yok", "Bu süreç üzerinde yetkiniz yok.")
        self.update_procs()


# ---------- KDE entegrasyonu
def install():
    home = os.path.expanduser("~")
    bin_dir = os.path.join(home, ".local", "bin")
    app_dir = os.path.join(home, ".local", "share", "applications")
    os.makedirs(bin_dir, exist_ok=True)
    os.makedirs(app_dir, exist_ok=True)
    target = os.path.join(bin_dir, APP_NAME)
    with open(os.path.abspath(__file__), "rb") as src, open(target, "wb") as dst:
        dst.write(src.read())
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP)

    desktop = f"""[Desktop Entry]
Type=Application
Name=btop
GenericName=Sistem İzleyici
Comment=btop tarzı kaynak izleyici (KDE Plasma)
Exec={target}
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;Qt;KDE;
Keywords=btop;cpu;ram;process;monitor;görev;
StartupWMClass={APP_NAME}
"""
    with open(os.path.join(app_dir, f"{APP_NAME}.desktop"), "w", encoding="utf-8") as f:
        f.write(desktop)
    for cmd in ("kbuildsycoca6", "kbuildsycoca5"):
        if os.system(f"command -v {cmd} >/dev/null 2>&1 && {cmd} >/dev/null 2>&1") == 0:
            break
    print(f"Kuruldu: {target}\nMenü girdisi: {app_dir}/{APP_NAME}.desktop")
    print("Global kısayol: Sistem Ayarları → Kısayollar → Özel Kısayollar → Komut:", target)


def main():
    if "--install" in sys.argv:
        install()
        return
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName(APP_NAME)  # Plasma'da gorev cubugu/simge eslesmesi
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
