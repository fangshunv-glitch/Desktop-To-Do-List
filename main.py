# -*- coding: utf-8 -*-
"""
今日事 · 多项目 deadline 台账
- 按项目分组，每个项目下若干待办，各自有截止日期
- 全部视图按截止日期排序，逾期 / 今天 / 明天 用颜色区分
- 置顶悬浮、可折叠、收进托盘；数据全在本地 data.json
"""
import sys
import os
import json
import uuid
import shutil
import datetime as dt
import re
import traceback
from pathlib import Path

from PySide6.QtCore import (Qt, QTimer, QPoint, QRectF, QSize, QDate, Signal,
                            QEvent)
from PySide6.QtGui import (QColor, QPainter, QPen, QFont, QIcon, QPixmap,
                           QPalette, QAction, QGuiApplication, QCursor,
                           QLinearGradient)
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QToolButton,
                               QScrollArea, QSizeGrip, QMenu, QSystemTrayIcon,
                               QGraphicsDropShadowEffect, QDialog, QCalendarWidget,
                               QPushButton, QSizePolicy)

APP_NAME = "今日事"
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent


def _user_data_dir():
    """可写的用户数据目录。

    默认放 %LOCALAPPDATA%\\TodayPlan，而不是 exe 同级目录，原因：
    1. 买家把程序解压到 C:\\Program Files 之类无写权限的位置时，
       同级目录写不进去，所有事项会在下次打开时凭空消失；
    2. 在压缩包里直接双击运行时，Windows 会解压到临时目录，
       关掉窗口数据就没了 —— 放用户目录可以避免；
    3. 覆盖更新 exe 时不会连数据一起覆盖掉。
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "TodayPlan"


def _resolve_data_path(local=None, user_dir=None):
    """决定 data.json 的位置，并兼容老的绿色版（数据在 exe 同级）。"""
    local = Path(local) if local else BASE_DIR / "data.json"
    target = (Path(user_dir) / "data.json") if user_dir else _user_data_dir() / "data.json"
    if local.exists() and not target.exists():
        # 老用户升级：把原数据搬过去，界面无缝衔接
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, target)
        except Exception:
            return local                     # 搬不动就继续用本地，至少能用
    if target.exists():
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        return target
    except Exception:
        return local                         # 用户目录也建不出来，退回同级


DATA_PATH = _resolve_data_path()
LOG_DIR = DATA_PATH.parent

# ---------- 配色：青绿主调，低饱和，看着不累 ----------
C_BG        = "#FFFFFF"
C_BG_BOT    = "#F6FBF8"          # 卡片底部极淡薄荷
C_PRIMARY   = "#17A673"          # 主绿
C_PRIMARY_D = "#0E8A5C"          # 深绿（hover / 强调）
C_TINT      = "#E7F6EF"          # 绿色浅底
C_TEXT      = "#1C2B25"          # 墨绿黑
C_SUB       = "#7E918A"          # 灰绿
C_LINE      = "#E9F1ED"
C_FILL      = "#F4F7F5"
C_RING      = "#CBDBD4"          # 未勾选的圆圈
C_DANGER    = "#D95C5C"
C_WARN      = "#C97A0E"
C_DONE      = "#A7B5AF"
C_STAR      = "#E9953C"

PALETTE = ["#17A673", "#3E8FD8", "#E9953C", "#D95C5C",
           "#8E6BC6", "#12A5A5", "#D6689E", "#5F7A70"]

# 卡片四周留白（给投影用），折叠后的窗口高度要把这部分算进去
CARD_MARGIN = 14
HEADER_H = 56
FOLD_H = HEADER_H + CARD_MARGIN * 2       # 折叠态窗口总高
MIN_OPEN_H = 300                          # 展开态最小高度：再矮输入框就会被压扁

WEEK_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 透明度可选档位（1.0 = 不透明）
OPACITY_PRESETS = [(1.0, "不透明"), (0.9, "90%"), (0.8, "80%"),
                   (0.7, "70%"), (0.6, "60%"), (0.5, "50%")]


def card_qss(a):
    """卡片白底的不透明度 a 只影响底板，文字始终实色，保证可读"""
    a = max(0.0, min(1.0, a))
    ai = int(round(a * 255))
    bi = int(round(max(a, 0.45) * 255))
    return (f"#card{{background:qlineargradient(spread:pad,x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 rgba(255,255,255,{ai}),"
            f"stop:0.62 rgba(252,254,253,{ai}),"
            f"stop:1 rgba(246,251,248,{ai}));"
            f"border:1px solid rgba(228,240,234,{bi});"
            "border-radius:16px;}")

MENU_QSS = ("QMenu{background:#fff;border:1px solid #E3EFE9;border-radius:10px;"
            "padding:5px;}"
            "QMenu::item{padding:7px 26px 7px 14px;border-radius:6px;font-size:9.5pt;"
            f"color:{C_TEXT};}}"
            f"QMenu::item:selected{{background:{C_TINT};color:{C_PRIMARY_D};}}"
            f"QMenu::separator{{height:1px;background:{C_LINE};margin:5px 9px;}}"
            "QMenu::item:disabled{color:#A9B8B1;}"
            "QMenu::indicator{width:0px;}")


def greeting():
    h = dt.datetime.now().hour
    if h < 5:
        return "夜深了"
    if h < 11:
        return "早上好"
    if h < 13:
        return "中午好"
    if h < 18:
        return "下午好"
    return "晚上好"


def now_str():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 数据层
# ============================================================
class Store:
    def __init__(self, path: Path):
        self.path = path
        self.on_error = None          # 保存失败时的回调（由界面挂上去提示用户）
        self._err_notified = False
        self.data = {
            "version": 2,
            "projects": [],
            "tasks": [],
            "settings": {"on_top": True, "x": None, "y": None, "h": 500,
                         "w": 380, "folded": False, "show_done": True,
                         "opacity": 0.85, "hover_opaque": True,
                         "filter": "all", "ui_ver": 2},
        }
        self.load()

    # ---------- 读入后的净化 ----------
    # 目的：任何一个字段被手改坏（null / 字符串 / 越界数字）都不能让程序
    # 启动即崩。买家一旦遇到打不开，基本等于退货，所以这里全部兜住。
    @staticmethod
    def _as_bool(v, default):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return default

    @staticmethod
    def _as_int(v, default, lo=None, hi=None):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return default
        if lo is not None and n < lo:
            n = lo
        if hi is not None and n > hi:
            n = hi
        return n

    @staticmethod
    def _as_float(v, default, lo=None, hi=None):
        try:
            n = float(v)
        except (TypeError, ValueError):
            return default
        if n != n:                    # NaN
            return default
        if lo is not None and n < lo:
            n = lo
        if hi is not None and n > hi:
            n = hi
        return n

    @staticmethod
    def _as_due(v):
        """截止日只接受 YYYY-MM-DD，其余一律清空，避免渲染时炸。"""
        if not isinstance(v, str):
            return None
        v = v.strip()[:10]
        try:
            dt.date.fromisoformat(v)
            return v
        except ValueError:
            return None

    def _clean_settings(self, raw):
        st = self.data["settings"]
        if not isinstance(raw, dict):
            return
        if "on_top" in raw:
            st["on_top"] = self._as_bool(raw["on_top"], True)
        if "folded" in raw:
            st["folded"] = self._as_bool(raw["folded"], False)
        if "show_done" in raw:
            st["show_done"] = self._as_bool(raw["show_done"], True)
        if "hover_opaque" in raw:
            st["hover_opaque"] = self._as_bool(raw["hover_opaque"], True)
        if "w" in raw:
            st["w"] = self._as_int(raw["w"], 380, 320, 1200)
        if "h" in raw:
            st["h"] = self._as_int(raw["h"], 500, MIN_OPEN_H, 2000)
        if "x" in raw:
            st["x"] = None if raw["x"] is None else self._as_int(raw["x"], None)
        if "y" in raw:
            st["y"] = None if raw["y"] is None else self._as_int(raw["y"], None)
        if "opacity" in raw:
            st["opacity"] = self._as_float(raw["opacity"], 0.85, 0.4, 1.0)
        if "ui_ver" in raw:
            st["ui_ver"] = self._as_int(raw["ui_ver"], 0, 0, 999)
        if "filter" in raw:
            f = raw["filter"]
            st["filter"] = f if isinstance(f, str) and f else "all"

    def _clean_projects(self, raw):
        out, seen = [], set()
        if not isinstance(raw, list):
            self.data["projects"] = []
            return
        for p in raw:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            if not isinstance(pid, str) or not pid or pid in seen:
                pid = self._new_pid()
            seen.add(pid)
            name = p.get("name")
            name = name.strip()[:20] if isinstance(name, str) else ""
            color = p.get("color")
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                color = PALETTE[len(out) % len(PALETTE)]
            out.append({"id": pid, "name": name or "未命名", "color": color})
        self.data["projects"] = out

    def _clean_tasks(self, raw, default_pid=""):
        out, seen = [], set()
        if not isinstance(raw, list):
            self.data["tasks"] = []
            return
        for t in raw:
            if not isinstance(t, dict):
                continue
            tid = t.get("id")
            if not isinstance(tid, str) or not tid or tid in seen:
                tid = "t" + uuid.uuid4().hex[:8]
            seen.add(tid)
            text = t.get("text")
            text = text if isinstance(text, str) else ("" if text is None else str(text))
            if not text.strip():
                continue                       # 空文字条目没有意义，直接丢
            pid = t.get("pid")
            pid = pid if isinstance(pid, str) else default_pid
            out.append({
                "id": tid,
                "pid": pid,
                "text": text[:500],
                "due": self._as_due(t.get("due")),
                "done": self._as_bool(t.get("done", False), False),
                "done_at": t.get("done_at") if isinstance(t.get("done_at"), str) else None,
                "star": self._as_bool(t.get("star", False), False),
                "created": t.get("created") if isinstance(t.get("created"), str) else now_str(),
                "notified": self._as_bool(t.get("notified", False), False),
            })
        self.data["tasks"] = out

    def load(self):
        if not self.path.exists():
            return
        try:
            # utf-8-sig：容忍记事本/PowerShell 等工具写入的 BOM，
            # 否则会解析失败被当成坏文件，数据看起来就"没了"
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print("读取失败:", e)
            try:
                self.path.with_suffix(".broken.json").write_bytes(self.path.read_bytes())
            except Exception:
                pass
            return
        raw = data
        if not isinstance(raw, dict):
            return
        if "projects" in raw or "tasks" in raw:
            self._clean_projects(raw.get("projects"))
            self._clean_settings(raw.get("settings"))
            self._clean_tasks(raw.get("tasks"))
        else:
            # 旧版（单清单）数据：全部装进「默认项目」
            tasks = []
            if isinstance(raw.get("tasks"), list):
                for t in raw["tasks"]:
                    if isinstance(t, dict):
                        if t.get("due"):
                            t["due"] = str(t["due"])[:10]   # "YYYY-MM-DD HH:MM" → 日期
                        tasks.append(t)
            if tasks:
                pid = self._new_pid()
                self.data["projects"].append({"id": pid, "name": "默认项目",
                                              "color": PALETTE[0]})
                self._clean_settings(raw.get("settings"))
                self._clean_tasks(tasks, default_pid=pid)
                self.save()

    def save(self):
        """原子写入。失败时一定让用户知道，绝不能悄悄丢数据。"""
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception as e:
            print("保存失败:", e)
            if self.on_error and not self._err_notified:
                self._err_notified = True
                try:
                    self.on_error(str(self.path), str(e))
                except Exception:
                    pass
            return False

    # ---------- 项目 ----------
    @staticmethod
    def _new_pid():
        return "p" + uuid.uuid4().hex[:8]

    @property
    def projects(self):
        return self.data["projects"]

    def project(self, pid):
        for p in self.projects:
            if p["id"] == pid:
                return p
        return None

    def add_project(self, name):
        color = PALETTE[len(self.projects) % len(PALETTE)]
        p = {"id": self._new_pid(), "name": name.strip()[:20], "color": color}
        self.projects.append(p)
        self.save()
        return p

    def rename_project(self, pid, name):
        p = self.project(pid)
        if p:
            p["name"] = name.strip()[:20]
            self.save()

    def delete_project(self, pid):
        # 项目下的任务转为「未分类」，不跟着一起删
        for t in self.data["tasks"]:
            if t.get("pid") == pid:
                t["pid"] = ""
        self.data["projects"] = [p for p in self.projects if p["id"] != pid]
        self.save()

    # ---------- 任务 ----------
    @property
    def tasks(self):
        return self.data["tasks"]

    def add(self, text, pid="", due=None, star=False):
        text = (text or "").strip()[:500]   # 超长文字会把列表撑变形
        if not text:
            return None
        t = {"id": "t" + uuid.uuid4().hex[:8], "pid": pid, "text": text,
             "due": due, "done": False, "star": star,
             "created": now_str(), "done_at": None, "notified": False}
        self.tasks.append(t)
        self.save()
        return t

    def get(self, tid):
        for t in self.tasks:
            if t["id"] == tid:
                return t
        return None

    def update(self, tid, **kw):
        t = self.get(tid)
        if t:
            t.update(kw)
            self.save()

    def toggle(self, tid):
        t = self.get(tid)
        if not t:
            return
        t["done"] = not t.get("done")
        t["done_at"] = now_str() if t["done"] else None
        if not t["done"]:
            t["notified"] = False
        self.save()

    def remove(self, tid):
        self.data["tasks"] = [t for t in self.tasks if t["id"] != tid]
        self.save()

    def clear_done(self, pid=None):
        def keep(t):
            if t.get("done") and (pid is None or t.get("pid") == pid):
                return False
            return True
        self.data["tasks"] = [t for t in self.tasks if keep(t)]
        self.save()

    @property
    def settings(self):
        return self.data["settings"]


# ============================================================
# 日期工具
# ============================================================
DATE_RE_1 = re.compile(r"(?:(?<=\s)|^)(\d{1,2})\s*[-/月]\s*(\d{1,2})日?(?=\s|$)")
DATE_RE_2 = re.compile(r"(-?\d{1,3})\s*天\s*(后|内|前)")
DATE_RE_3 = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?")
DATE_RE_4 = re.compile(r"(?:(?<=\s)|^)(下)?(?:周|星期|礼拜)([一二三四五六日天])(?=\s|$)")


def _cut(text, m):
    """把匹配到的日期片段从正文里摘掉，顺手收掉多余空格。"""
    rest = (text[:m.start()] + " " + text[m.end():]).strip()
    return re.sub(r"\s{2,}", " ", rest)


def parse_due(text):
    """从输入里抽截止日期，返回 (剩余文本, date 或 None)

    识别顺序有讲究：先长短后短，否则「2027-01-31」会被当成「01-31」，
    「下周一」会被当成「周一」。
    """
    today = dt.date.today()

    # 完整年月日：2027-01-31 / 2027/1/31 / 2027年1月31日
    m = DATE_RE_3.search(text)
    if m:
        try:
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return _cut(text, m), d
        except ValueError:
            pass

    # 今天 / 明天 / 后天 / 大后天（「大后天」必须排在「后天」前面）
    m = re.search(r"(大后天|今天|明天|后天)", text)
    if m:
        off = {"大后天": 3, "今天": 0, "明天": 1, "后天": 2}[m.group(1)]
        return _cut(text, m), today + dt.timedelta(days=off)

    # 3天后 / 3天内 / 3天前 / -3天后
    m = DATE_RE_2.search(text)
    if m:
        n = int(m.group(1))
        if m.group(2) == "前":
            n = -abs(n)
        return _cut(text, m), today + dt.timedelta(days=n)

    # 11-06 / 11/6 / 11月6日
    m = DATE_RE_1.search(text)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            try:
                d = dt.date(today.year, mm, dd)
                if d < today - dt.timedelta(days=180):   # 明显是过去的月份 → 算明年
                    d = dt.date(today.year + 1, mm, dd)
                rest = _cut(text, m)
                if rest:
                    return rest, d
            except ValueError:
                pass
    # 周五 / 下周一 / 星期三
    m = DATE_RE_4.search(text)
    if m:
        ch = "日" if m.group(2) in ("日", "天") else m.group(2)
        wd = "一二三四五六日".index(ch)
        if m.group(1):                      # 「下周一」= 下周一的日期
            mon = today - dt.timedelta(days=today.weekday())
            d = mon + dt.timedelta(days=7 + wd)
        else:
            d = today + dt.timedelta(days=(wd - today.weekday()) % 7)
        return _cut(text, m), d

    return text, None


def wrap_soft(text, n=16):
    """给没有空格的超长串（链接、订单号、连续英文）插入零宽空格。

    QLabel 的自动换行只在空格和汉字边界处断行，一串 200 个字母会直接
    横向溢出、把窗口撑破。插 U+200B 后视觉上一个字都没变，但能折行。
    """
    if not isinstance(text, str) or len(text) < n:
        return text
    out, run = [], 0
    for ch in text:
        out.append(ch)
        if ch.isspace():
            run = 0
        else:
            run += 1
            if run >= n:
                out.append("\u200b")
                run = 0
    return "".join(out)


def parse_date_only(s):
    """把「明天」「周五」「11-06」「3天后」「2026-12-01」解析成 date；认不出返回 None"""
    s = (s or "").strip()
    if not s:
        return None
    today = dt.date.today()

    m = re.search(r"(大后天|今天|明天|后天)", s)
    if m:
        off = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}[m.group(1)]
        return today + dt.timedelta(days=off)

    m = re.search(r"(-?\d{1,3})\s*天\s*(后|内|前)", s)
    if m:
        n = int(m.group(1))
        if m.group(2) == "前":
            n = -abs(n)
        return today + dt.timedelta(days=n)

    m = re.search(r"(下)?(?:周|星期|礼拜)([一二三四五六日天])", s)
    if m:
        ch = "日" if m.group(2) in ("日", "天") else m.group(2)
        wd = "一二三四五六日".index(ch)
        if m.group(1):          # 「下周一」= 本周一往后推 7 天
            mon = today - dt.timedelta(days=today.weekday())
            return mon + dt.timedelta(days=7 + wd)
        return today + dt.timedelta(days=(wd - today.weekday()) % 7)

    m = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.search(r"(\d{1,2})\s*[-/.月]\s*(\d{1,2})", s)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            try:
                d = dt.date(today.year, mm, dd)
                if d < today - dt.timedelta(days=180):
                    d = dt.date(today.year + 1, mm, dd)
                return d
            except ValueError:
                return None
    return None


def due_info(due):
    """返回 (显示文字, 状态)"""
    if not due:
        return "", "none"
    try:
        d = dt.date.fromisoformat(due)
    except Exception:
        return due, "normal"
    delta = (d - dt.date.today()).days
    if delta < 0:
        return f"逾期 {-delta} 天", "overdue"
    if delta == 0:
        return "今天截止", "today"
    if delta == 1:
        return "明天截止", "tomorrow"
    if delta <= 7:
        return f"剩 {delta} 天", "soon"
    return d.strftime("%m-%d"), "normal"


DUE_COLORS = {
    "overdue":  ("#FCECEC", "#CE4B4B"),
    "today":    ("#FFF2E0", "#B96A05"),
    "tomorrow": ("#E7F6EF", "#0E8A5C"),
    "soon":     ("#F1F6F3", "#5F7A70"),
    "normal":   ("#F1F6F3", "#7E918A"),
}


# ============================================================
# 小组件：品牌标 / 细进度条 / 空状态插画
# ============================================================
class LogoMark(QWidget):
    """标题栏左侧的小方块图标：绿色渐变圆角 + 白色对勾"""
    def __init__(self, size=22, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        r = QRectF(0.5, 0.5, w - 1, w - 1)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, QColor("#33C692"))
        g.setColorAt(1.0, QColor("#0E8A5C"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, w * 0.32, w * 0.32)

        pen = QPen(QColor(255, 255, 255, 240), w * 0.095)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        k = w / 22.0
        p.drawLine(QPoint(int(6.4 * k), int(11.4 * k)),
                   QPoint(int(9.6 * k), int(14.6 * k)))
        p.drawLine(QPoint(int(9.6 * k), int(14.6 * k)),
                   QPoint(int(15.8 * k), int(7.6 * k)))


class ThinBar(QWidget):
    """底部的完成度细进度条"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self._v = 0.0

    def setValue(self, v):
        v = max(0.0, min(1.0, float(v)))
        if abs(v - self._v) > 0.001:
            self._v = v
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        if w <= 0:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#EAF3EE"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        if self._v <= 0:
            return
        bw = max(h, w * self._v)
        g = QLinearGradient(0, 0, bw, 0)
        g.setColorAt(0.0, QColor("#5FD3A5"))
        g.setColorAt(1.0, QColor(C_PRIMARY))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, bw, h), h / 2, h / 2)


class EmptyArt(QWidget):
    """空状态的小插画：薄荷圆底 + 白色卡片 + 绿色对勾 + 几个小点"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(92, 92)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#EDF8F2"))
        p.drawEllipse(QPoint(int(cx), int(cy)), 42, 42)

        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPoint(int(cx), int(cy)), 27, 27)

        pen = QPen(QColor(C_PRIMARY), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPoint(int(cx - 8), int(cy + 0.5)),
                   QPoint(int(cx - 2), int(cy + 6.5)))
        p.drawLine(QPoint(int(cx - 2), int(cy + 6.5)),
                   QPoint(int(cx + 8.5), int(cy - 6)))

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#BFE8D6"))
        p.drawEllipse(QPoint(int(cx + 30), int(cy - 26)), 4, 4)
        p.setBrush(QColor("#D9EFE5"))
        p.drawEllipse(QPoint(int(cx - 31), int(cy + 22)), 3, 3)
        p.setBrush(QColor("#CDEDE0"))
        p.drawEllipse(QPoint(int(cx + 24), int(cy + 30)), 2, 2)


class EmptyView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 0, 20, 0)
        v.setSpacing(0)
        v.addStretch(1)
        v.addWidget(EmptyArt(), 0, Qt.AlignHCenter)
        v.addSpacing(12)

        self.t1 = QLabel()
        self.t1.setAlignment(Qt.AlignCenter)
        self.t1.setWordWrap(True)
        f1 = QFont(self.t1.font())
        f1.setPointSizeF(9.8)
        f1.setWeight(QFont.DemiBold)
        self.t1.setFont(f1)
        self.t1.setStyleSheet(f"color:{C_TEXT};background:transparent;")
        v.addWidget(self.t1)

        v.addSpacing(5)
        self.t2 = QLabel()
        self.t2.setAlignment(Qt.AlignCenter)
        self.t2.setWordWrap(True)
        f2 = QFont(self.t2.font())
        f2.setPointSizeF(8.8)
        self.t2.setFont(f2)
        self.t2.setStyleSheet(f"color:{C_SUB};background:transparent;")
        v.addWidget(self.t2)
        v.addStretch(1)

    def set_data(self, title, sub=""):
        self.t1.setText(title)
        self.t2.setText(sub)
        self.t2.setVisible(bool(sub))


# ============================================================
# 圆形勾选
# ============================================================
class CircleCheck(QWidget):
    clicked = Signal()

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._hover = False
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def isChecked(self):
        return self._checked

    def setChecked(self, v):
        self._checked = v
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        d = 18.0
        r = QRectF((self.width() - d) / 2, (self.height() - d) / 2, d, d)
        if self._checked:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0.0, QColor("#2FBE8B"))
            g.setColorAt(1.0, QColor(C_PRIMARY_D))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(r)
            pen = QPen(QColor("#FFFFFF"), 1.9)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            x0, y0 = r.left(), r.top()
            p.drawLine(QPoint(int(x0 + 4.4), int(y0 + 9.2)),
                       QPoint(int(x0 + 7.6), int(y0 + 12.4)))
            p.drawLine(QPoint(int(x0 + 7.6), int(y0 + 12.4)),
                       QPoint(int(x0 + 13.4), int(y0 + 5.8)))
        else:
            ring = QColor(C_PRIMARY) if self._hover else QColor(C_RING)
            p.setPen(QPen(ring, 1.6))
            p.setBrush(QColor("#F8FCFA") if self._hover else Qt.NoBrush)
            p.drawEllipse(r.adjusted(0.75, 0.75, -0.75, -0.75))


# ============================================================
# 横向滚动区（项目标签栏用，滚轮直接横滚）
# ============================================================
class HScroll(QScrollArea):
    def wheelEvent(self, e):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - e.angleDelta().y() // 2)
        e.accept()


# ============================================================
# 日历弹窗
# ============================================================
class DatePick(QDialog):
    def __init__(self, current=None, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.result_date = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        card = QFrame()
        card.setObjectName("dc")
        card.setStyleSheet(f"""
            #dc {{ background:#fff; border-radius:14px; border:1px solid #E3EFE9; }}
            QCalendarWidget QWidget {{ alternate-background-color:#fff; }}
            QCalendarWidget QAbstractItemView:enabled {{
                background:#fff; color:{C_TEXT};
                selection-background-color:{C_PRIMARY};
                selection-color:#fff; outline:0; font-size:9pt; }}
            QCalendarWidget QAbstractItemView:disabled {{ color:#CBD8D2; }}
            QCalendarWidget QToolButton {{
                color:{C_TEXT}; background:transparent; border:none;
                border-radius:6px; padding:4px 8px; font-size:9.5pt; }}
            QCalendarWidget QToolButton:hover {{ background:{C_TINT}; }}
            QCalendarWidget QMenu {{ background:#fff; }}
            QCalendarWidget QSpinBox {{ background:#fff; color:{C_TEXT}; }}
            QCalendarWidget #qt_calendar_navigationbar {{ background:#fff;
                border-bottom:1px solid {C_LINE}; }}
        """)
        outer.addWidget(card)

        v = QVBoxLayout(card)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        self.cal = QCalendarWidget()
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.cal.setFixedSize(292, 232)
        if current:
            self.cal.setSelectedDate(QDate(current.year, current.month, current.day))
        else:
            self.cal.setSelectedDate(QDate.currentDate())
        v.addWidget(self.cal)

        row = QHBoxLayout()
        row.setSpacing(6)
        for text, days in (("今天", 0), ("明天", 1), ("+7天", 7)):
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{border:1px solid {C_RING};background:#FFFFFF;"
                f"color:{C_PRIMARY_D};border-radius:8px;padding:5px 11px;"
                "font-size:9pt;font-weight:600;}"
                f"QPushButton:hover{{background:{C_TINT};border-color:{C_PRIMARY};}}")
            b.clicked.connect(lambda _, d=days: self._pick(d))
            row.addWidget(b)
        row.addStretch(1)

        clear = QPushButton("清除")
        clear.setCursor(Qt.PointingHandCursor)
        clear.setStyleSheet(
            f"QPushButton{{border:1px solid transparent;background:transparent;"
            f"color:{C_SUB};border-radius:8px;padding:5px 9px;font-size:9pt;}}"
            "QPushButton:hover{background:#FCEDED;color:#CE4B4B;}")
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        v.addLayout(row)

        self.cal.clicked.connect(self._accept_date)

    def _pick(self, days):
        self.result_date = dt.date.today() + dt.timedelta(days=days)
        self.accept()

    def _clear(self):
        self.result_date = None
        self.accept()

    def _accept_date(self, qd):
        self.result_date = dt.date(qd.year(), qd.month(), qd.day())
        self.accept()


# ============================================================
# 自绘弹窗：不用系统对话框，避免被其它置顶窗口压住、也方便拖动
# ============================================================
class CardDialog(QDialog):
    def __init__(self, parent=None, title="", width=340):
        super().__init__(parent)
        # 关键：置顶 + 无边框。系统原生对话框在贴屏幕右边的卡片旁边，
        # 会被通知面板等置顶窗口盖住，标题栏也抓不到。
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setWindowTitle(title)
        self._drag = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 20)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("dlgcard")
        card.setStyleSheet(
            "#dlgcard{background:#FFFFFF;border:1px solid #E3EFE9;"
            "border-radius:14px;}")
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(30)
        sh.setOffset(0, 8)
        sh.setColor(QColor(16, 44, 34, 64))
        card.setGraphicsEffect(sh)
        outer.addWidget(card)
        self.card = card

        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(9)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{C_PRIMARY};font-size:9.5pt;")
        head.addWidget(dot, 0, Qt.AlignVCenter)
        tl = QLabel(title)
        tf = QFont(tl.font())
        tf.setPointSizeF(10.2)
        tf.setWeight(QFont.DemiBold)
        tl.setFont(tf)
        tl.setStyleSheet(f"color:{C_TEXT};background:transparent;")
        head.addWidget(tl, 1, Qt.AlignVCenter)
        xb = QToolButton()
        xb.setText("×")
        xb.setCursor(Qt.PointingHandCursor)
        xb.setFixedSize(22, 22)
        xb.setStyleSheet(
            f"QToolButton{{border:none;background:transparent;color:{C_SUB};"
            "border-radius:11px;font-size:13pt;padding-bottom:2px;}"
            f"QToolButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")
        xb.clicked.connect(self.reject)
        head.addWidget(xb, 0, Qt.AlignVCenter)
        v.addLayout(head)

        ln = QFrame()
        ln.setFixedHeight(1)
        ln.setStyleSheet(f"background:{C_LINE};border:none;")
        v.addWidget(ln)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 2, 0, 0)
        self.body.setSpacing(8)
        v.addLayout(self.body)

        self.foot = QHBoxLayout()
        self.foot.setContentsMargins(0, 2, 0, 0)
        self.foot.setSpacing(8)
        self.foot.addStretch(1)
        v.addLayout(self.foot)

        self.setFixedWidth(width)

    # ---- 拖动：整块面板都能拖 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)

    # ---- 摆到屏幕正中（避开屏幕边角的系统弹层） ----
    def place(self):
        self.adjustSize()
        scr = None
        if self.parent() is not None and hasattr(self.parent(), "screen"):
            scr = self.parent().screen()
        scr = scr or QGuiApplication.primaryScreen()
        area = scr.availableGeometry()
        g = self.frameGeometry()
        x = area.center().x() - g.width() // 2
        y = area.center().y() - g.height() // 2 - 40
        x = max(area.left() + 16, min(x, area.right() - g.width() - 15))
        y = max(area.top() + 16, min(y, area.bottom() - g.height() - 15))
        self.move(x, y)

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()


def _dlg_btn(text, primary=True, danger=False):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(32)
    if danger:
        bg, hov = C_DANGER, "#C24B4B"
        style = (f"QPushButton{{border:none;background:{bg};color:#fff;"
                 "border-radius:8px;padding:6px 18px;font-size:9pt;"
                 f"font-weight:600;}}QPushButton:hover{{background:{hov};}}")
    elif primary:
        style = (f"QPushButton{{border:none;background:{C_PRIMARY};color:#fff;"
                 "border-radius:8px;padding:6px 18px;font-size:9pt;"
                 f"font-weight:600;}}QPushButton:hover{{background:{C_PRIMARY_D};}}")
    else:
        style = (f"QPushButton{{border:none;background:{C_FILL};color:#5F7A70;"
                 "border-radius:8px;padding:6px 16px;font-size:9pt;}"
                 f"QPushButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")
    b.setStyleSheet(style)
    return b


def ask_text(parent, title, label, initial="", placeholder="", width=340):
    """返回 (文本, 是否确定)；取消或空串时文本为空"""
    d = CardDialog(parent, title, width)
    lab = QLabel(label)
    lab.setStyleSheet(f"color:{C_SUB};font-size:8.8pt;background:transparent;")
    d.body.addWidget(lab)

    ed = QLineEdit(initial)
    ed.setPlaceholderText(placeholder)
    ed.setMinimumHeight(34)
    ed.setStyleSheet(
        f"QLineEdit{{background:#fff;border:1px solid {C_LINE};border-radius:9px;"
        f"padding:7px 10px;color:{C_TEXT};font-size:9.5pt;}}"
        f"QLineEdit:focus{{border:1px solid {C_PRIMARY};}}"
        f"QLineEdit{{selection-background-color:{C_PRIMARY};selection-color:#fff;}}")
    d.body.addWidget(ed)

    ok = _dlg_btn("确定")
    cancel = _dlg_btn("取消", primary=False)
    d.foot.addWidget(cancel)
    d.foot.addWidget(ok)
    ok.setDefault(True)
    ok.clicked.connect(d.accept)
    cancel.clicked.connect(d.reject)
    ed.returnPressed.connect(d.accept)

    d.place()
    QTimer.singleShot(0, lambda: (ed.setFocus(), ed.selectAll()))
    if d.exec() == QDialog.Accepted:
        t = ed.text().strip()
        if t:
            return t, True
    return "", False


def _mini_btn(text):
    """弹窗里的小圆角按钮：白底 + 绿字 + 描边"""
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        f"QPushButton{{border:1px solid {C_RING};background:#FFFFFF;"
        f"color:{C_PRIMARY_D};border-radius:8px;padding:4px 11px;"
        "font-size:8.8pt;font-weight:600;}"
        f"QPushButton:hover{{background:{C_TINT};border-color:{C_PRIMARY};}}")
    return b


def _le_qss():
    return (f"QLineEdit{{background:#fff;border:1px solid {C_LINE};"
            f"border-radius:9px;padding:7px 10px;color:{C_TEXT};"
            "font-size:9.5pt;}"
            f"QLineEdit:focus{{border:1px solid {C_PRIMARY};}}"
            f"QLineEdit{{selection-background-color:{C_PRIMARY};"
            "selection-color:#fff;}")


def ask_task(parent, title, text, due=None, width=390):
    """一次改「内容 + 截止日期」。返回 (新内容, date 或 None)；取消返回 (None, None)"""
    d = CardDialog(parent, title, width)
    st = {"due": due, "ok": False}

    def cap(t):
        l = QLabel(t)
        l.setStyleSheet(
            f"color:{C_SUB};font-size:8.8pt;background:transparent;")
        return l

    d.body.addWidget(cap("内容"))
    ed = QLineEdit(text)
    ed.setMinimumHeight(34)
    ed.setStyleSheet(_le_qss())
    d.body.addWidget(ed)

    top = QHBoxLayout()
    top.setContentsMargins(0, 4, 0, 0)
    top.addWidget(cap("截止日期"), 1)
    d.body.addLayout(top)

    drow = QHBoxLayout()
    drow.setSpacing(6)
    de = QLineEdit()
    de.setMinimumHeight(32)
    de.setPlaceholderText("留空＝不设 / 明天 / 11-06")
    de.setStyleSheet(_le_qss())
    drow.addWidget(de, 1)
    cal = _mini_btn("日历…")
    drow.addWidget(cal, 0)
    d.body.addLayout(drow)

    tip = QLabel("")
    tip.setWordWrap(True)
    tip.setStyleSheet(
        f"color:{C_SUB};font-size:8.4pt;background:transparent;")
    d.body.addWidget(tip)

    chips = QHBoxLayout()
    chips.setSpacing(6)
    for lb, off in (("今天", 0), ("明天", 1), ("+7天", 7)):
        b = _mini_btn(lb)
        b.clicked.connect(
            lambda _, k=off: _put(dt.date.today() + dt.timedelta(days=k)))
        chips.addWidget(b)
    b_none = _mini_btn("不设")
    b_none.clicked.connect(lambda: _put(None))
    chips.addWidget(b_none)
    chips.addStretch(1)
    d.body.addLayout(chips)

    def _put(dd):
        de.setText("" if dd is None
                   else f"{dd.month:02d}-{dd.day:02d}")

    def _sync():
        raw = de.text().strip()
        if not raw:
            st["due"] = None
            tip.setText("不设截止日")
            tip.setStyleSheet(
                f"color:{C_SUB};font-size:8.4pt;background:transparent;")
            return True
        dd = parse_date_only(raw)
        if dd is None:
            st["due"] = None
            tip.setText("认不出这个日期：试试「明天」「周五」「11-06」「3天后」")
            tip.setStyleSheet(
                f"color:{C_DANGER};font-size:8.4pt;background:transparent;")
            return False
        st["due"] = dd
        delta = (dd - dt.date.today()).days
        rel = ("今天" if delta == 0 else "明天" if delta == 1 else
               f"{delta} 天后" if delta > 1 else f"已过去 {-delta} 天")
        tip.setText(f"→ {dd.strftime('%Y-%m-%d')} "
                    f"{WEEK_CN[dd.weekday()]}（{rel}）")
        tip.setStyleSheet(
            f"color:{C_PRIMARY_D};font-size:8.4pt;font-weight:600;"
            "background:transparent;")
        return True

    def _open_cal():
        dlg = DatePick(st["due"], d)
        dlg.adjustSize()
        w = max(dlg.size().width(), dlg.sizeHint().width())
        h = max(dlg.size().height(), dlg.sizeHint().height())
        scr = ((d.screen() or QGuiApplication.primaryScreen())
               .availableGeometry())
        c = d.geometry().center()
        x = max(scr.left() + 8, min(c.x() - w // 2, scr.right() - w - 8))
        y = max(scr.top() + 8, min(c.y() - h // 2, scr.bottom() - h - 8))
        dlg.move(x, y)
        if dlg.exec() == QDialog.Accepted:
            _put(dlg.result_date)

    cal.clicked.connect(_open_cal)
    de.textChanged.connect(_sync)

    ok = _dlg_btn("保存")
    cancel = _dlg_btn("取消", primary=False)
    d.foot.addWidget(cancel)
    d.foot.addWidget(ok)
    ok.setDefault(True)

    def _do_ok():
        if not ed.text().strip():
            ed.setFocus()
            return
        if not _sync():
            de.setFocus()
            return
        st["ok"] = True
        d.accept()

    ok.clicked.connect(_do_ok)
    cancel.clicked.connect(d.reject)
    ed.returnPressed.connect(_do_ok)
    de.returnPressed.connect(_do_ok)

    _put(due)
    _sync()
    d.place()

    def _focus_content():
        ed.setFocus()
        ed.setCursorPosition(len(ed.text()))

    QTimer.singleShot(0, _focus_content)
    if d.exec() == QDialog.Accepted and st["ok"]:
        return ed.text().strip(), st["due"]
    return None, None


def ask_confirm(parent, title, message, ok_text="确定", danger=True, width=350):
    d = CardDialog(parent, title, width)
    lab = QLabel(message)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color:{C_TEXT};font-size:9.2pt;background:transparent;")
    d.body.addWidget(lab)

    ok = _dlg_btn(ok_text, primary=not danger, danger=danger)
    cancel = _dlg_btn("取消", primary=False)
    d.foot.addWidget(cancel)
    d.foot.addWidget(ok)
    ok.setDefault(True)
    ok.clicked.connect(d.accept)
    cancel.clicked.connect(d.reject)

    d.place()
    return d.exec() == QDialog.Accepted


# ============================================================
# 任务行
# ============================================================
class TaskRow(QWidget):
    toggled = Signal(str)
    deleted = Signal(str)
    edited = Signal(str, str)
    starToggled = Signal(str)
    dueRequested = Signal(str)
    editRequested = Signal(str)     # 打开「内容 + 日期」编辑窗

    def __init__(self, task, proj=None, show_proj=True, parent=None):
        super().__init__(parent)
        self.task = task
        self.proj = proj
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("background: transparent;")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 9, 3, 9)
        lay.setSpacing(10)

        self.check = CircleCheck(task.get("done", False))
        self.check.clicked.connect(lambda: self.toggled.emit(task["id"]))
        lay.addWidget(self.check, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(3)

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(4)
        self.star_lbl = QLabel("★")
        self.star_lbl.setVisible(False)
        fs = QFont(self.star_lbl.font())
        fs.setPointSizeF(9.5)
        self.star_lbl.setFont(fs)
        line.addWidget(self.star_lbl, 0, Qt.AlignTop)

        self.lbl = QLabel()
        self.lbl.setWordWrap(True)
        self.lbl.setTextFormat(Qt.PlainText)
        self.lbl.setCursor(Qt.PointingHandCursor)
        line.addWidget(self.lbl, 1)
        mid.addLayout(line)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(7)

        self.proj_lbl = QLabel()
        self.proj_lbl.setVisible(False)
        fp = QFont(self.proj_lbl.font())
        fp.setPointSizeF(8.4)
        self.proj_lbl.setFont(fp)
        if show_proj:
            meta.addWidget(self.proj_lbl, 0)

        self.pill = QLabel()
        fp2 = QFont(self.pill.font())
        fp2.setPointSizeF(8.4)
        self.pill.setFont(fp2)
        self.pill.setCursor(Qt.PointingHandCursor)
        self.pill.setToolTip("点这里改这条的截止日期")
        self.pill.installEventFilter(self)
        meta.addWidget(self.pill, 0)
        meta.addStretch(1)
        mid.addLayout(meta)

        lay.addLayout(mid, 1)

        self.btn = QToolButton()
        self.btn.setText("×")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedSize(20, 20)
        self.btn.setStyleSheet(
            f"QToolButton{{border:none;background:transparent;color:#C4D2CC;"
            "border-radius:10px;font-size:15pt;padding-bottom:3px;}"
            "QToolButton:hover{background:#FCEDED;color:#CE4B4B;}")
        self.btn.setVisible(False)
        self.btn.clicked.connect(lambda: self.deleted.emit(task["id"]))
        lay.addWidget(self.btn, 0, Qt.AlignTop)

        self.refresh(show_proj)

    def refresh(self, show_proj=True):
        t = self.task
        done = bool(t.get("done"))
        star = bool(t.get("star"))
        raw = t.get("text", "")

        self.star_lbl.setVisible(star)
        self.star_lbl.setStyleSheet(
            f"color:{'#CBD8D2' if done else C_STAR};background:transparent;")

        self.lbl.setTextFormat(Qt.PlainText)
        self.lbl.setText(wrap_soft(raw))
        f = QFont(self.lbl.font())
        f.setPointSizeF(9.6)
        f.setStrikeOut(done)
        f.setWeight(QFont.DemiBold if (star and not done) else QFont.Normal)
        self.lbl.setFont(f)
        color = C_DONE if done else ("#9A6100" if star else C_TEXT)
        self.lbl.setStyleSheet(f"color:{color};background:transparent;")
        self.lbl.setToolTip(raw)

        # 项目名
        if show_proj:
            if self.proj:
                self.proj_lbl.setText("● " + self.proj.get("name", ""))
                c = self.proj.get("color", C_SUB) if not done else "#CBD8D2"
                self.proj_lbl.setStyleSheet(
                    f"color:{c};background:transparent;font-size:8.4pt;")
            else:
                self.proj_lbl.setText("● 未分类")
                self.proj_lbl.setStyleSheet(
                    f"color:{C_SUB};background:transparent;font-size:8.4pt;")
            self.proj_lbl.setVisible(True)
        else:
            self.proj_lbl.setVisible(False)

        # 截止
        label, state = due_info(t.get("due"))
        if not label or done:
            self.pill.setVisible(False)
        else:
            bg, fg = DUE_COLORS.get(state, DUE_COLORS["normal"])
            self.pill.setText(label)
            self.pill.setStyleSheet(
                f"background:{bg};color:{fg};border-radius:7px;"
                f"padding:1px 7px;font-size:8.4pt;font-weight:600;")
            self.pill.setVisible(True)

    def enterEvent(self, e):
        self.btn.setVisible(True)
        self.setStyleSheet("background:#F5FAF7;border-radius:10px;")
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.btn.setVisible(False)
        self.setStyleSheet("background:transparent;")
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e):
        # 双击整行 = 改内容 + 改截止日期
        self.editRequested.emit(self.task["id"])

    def eventFilter(self, obj, e):
        # 点日期小标签直接改日期
        if obj is self.pill and e.type() == QEvent.MouseButtonRelease:
            if not self.task.get("done"):
                self.dueRequested.emit(self.task["id"])
                return True
        return super().eventFilter(obj, e)

    def contextMenuEvent(self, e):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        a_undo = None
        if self.task.get("done"):
            a_undo = menu.addAction("撤销完成（放回待办）")
            menu.addSeparator()
        a_star = menu.addAction("取消重要" if self.task.get("star") else "标为重要")
        a_edit = menu.addAction("编辑内容与日期…")
        a_due = menu.addAction("只改截止日期…" if self.task.get("due")
                               else "设置截止日期…")
        a_clr = menu.addAction("清除截止日期")
        a_move = menu.addMenu("移动到项目")
        a_move.setStyleSheet(MENU_QSS)
        moves = []
        for p in self.window().store.projects if hasattr(self.window(), "store") else []:
            act = a_move.addAction(p["name"])
            moves.append((act, p["id"]))
        menu.addSeparator()
        a_del = menu.addAction("删除")

        act = menu.exec(e.globalPos())
        if a_undo is not None and act == a_undo:
            self.toggled.emit(self.task["id"])
        elif act == a_star:
            self.starToggled.emit(self.task["id"])
        elif act == a_edit:
            self.editRequested.emit(self.task["id"])
        elif act == a_due:
            self.dueRequested.emit(self.task["id"])
        elif act == a_clr:
            self.edited.emit(self.task["id"], "|clear-due|")
        elif act == a_del:
            self.deleted.emit(self.task["id"])
        else:
            for a, pid in moves:
                if act == a:
                    self.edited.emit(self.task["id"], f"|move|{pid}")
                    break


# ============================================================
# 主窗口
# ============================================================
class Planner(QWidget):
    def __init__(self):
        super().__init__()
        self.store = Store(DATA_PATH)
        self._pending_save_error = None
        self.store.on_error = lambda p, e: setattr(self, "_pending_save_error", (p, e))
        st = self.store.settings

        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(int(st.get("w") or 380), int(st.get("h") or 500))
        self.setMinimumSize(320, MIN_OPEN_H)
        if st.get("on_top", True):
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        self._drag_pos = None
        self._folded = bool(st.get("folded"))
        # 老版本默认把「已完成」藏起来，点了圆圈就"消失"，改成默认显示并迁移一次
        if int(st.get("ui_ver") or 0) < 2:
            st["show_done"] = True
            st["ui_ver"] = 2
            self.store.save()
        self._show_done = bool(st.get("show_done", True))
        self._filter = st.get("filter") or "all"
        self._opacity = float(st.get("opacity", 0.85))
        self._hover_opaque = bool(st.get("hover_opaque", True))
        # 上次看的是不是已经删掉的项目？回退到全部
        if self._filter not in ("all", "") and not self.store.project(self._filter):
            self._filter = "all"
        self._add_pid = ""
        self._add_due = None

        self._build_ui()
        self._build_tray()
        self._restore_pos()
        self.reload()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check_reminders)
        self.timer.start(20000)

        self.date_timer = QTimer(self)
        self.date_timer.timeout.connect(self._on_day_tick)
        self.date_timer.start(60 * 1000)
        self._today = dt.date.today()

        self._apply_fold()

        # 透明度：只让白底面板半透明，文字保持实色
        self._hovering = False
        self._card_alpha = -1.0
        self._refresh_card()
        self._op_timer = QTimer(self)
        self._op_timer.timeout.connect(self._check_hover_opacity)
        self._op_timer.start(180)

    # ---------------- 界面 ----------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(CARD_MARGIN, CARD_MARGIN, CARD_MARGIN, CARD_MARGIN)
        outer.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setStyleSheet(card_qss(self._opacity))
        self._set_card_shadow(True)
        outer.addWidget(self.card)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 悬浮提示条（划掉/恢复的即时反馈）
        self.toast = QLabel(self.card)
        self.toast.setStyleSheet(
            "background:rgba(28,43,37,235);color:#FFFFFF;border-radius:12px;"
            "padding:7px 13px;font-size:8.8pt;")
        self.toast.setVisible(False)
        self.toast.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self.toast.setVisible(False))

        # ---- 标题栏 ----
        self.header = QWidget()
        self.header.setFixedHeight(HEADER_H)
        self.header.setCursor(Qt.OpenHandCursor)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(16, 0, 10, 0)
        h.setSpacing(9)

        h.addWidget(LogoMark(23), 0, Qt.AlignVCenter)

        cap = QVBoxLayout()
        cap.setContentsMargins(0, 0, 0, 0)
        cap.setSpacing(0)

        self.title = QLabel(APP_NAME)
        f = QFont(self.title.font())
        f.setPointSizeF(10.5)
        f.setWeight(QFont.DemiBold)
        self.title.setFont(f)
        self.title.setStyleSheet(f"color:{C_TEXT};background:transparent;")
        cap.addWidget(self.title)

        self.date_lbl = QLabel()
        self.date_lbl.setStyleSheet(f"color:{C_SUB};font-size:8.2pt;background:transparent;")
        cap.addWidget(self.date_lbl)
        h.addLayout(cap)
        h.addStretch(1)

        self.b_op = self._tool_btn("透", "透明度：鼠标移入会自动变清晰")
        self.b_op.clicked.connect(self._show_opacity_menu)
        h.addWidget(self.b_op)
        self.b_pin = self._tool_btn("钉", "始终置顶")
        self.b_pin.clicked.connect(self._toggle_on_top)
        h.addWidget(self.b_pin)
        self.b_fold = self._tool_btn("—", "折叠")
        self.b_fold.clicked.connect(self._toggle_fold)
        h.addWidget(self.b_fold)
        self.b_close = self._tool_btn("×", "收进托盘")
        self.b_close.clicked.connect(self._hide_to_tray)
        h.addWidget(self.b_close)
        v.addWidget(self.header)

        # ---- 主体 ----
        self.body = QWidget()
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(0)

        # 项目 Tab
        self.tab_scroll = HScroll()
        self.tab_scroll.setWidgetResizable(False)
        self.tab_scroll.setFixedHeight(40)
        self.tab_scroll.setFrameShape(QFrame.NoFrame)
        self.tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tab_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}")
        self.tab_host = QWidget()
        self.tab_host.setStyleSheet("background:transparent;")
        self.tab_lay = QHBoxLayout(self.tab_host)
        self.tab_lay.setContentsMargins(12, 2, 10, 2)
        self.tab_lay.setSpacing(5)
        self.tab_lay.addStretch(1)
        self.tab_scroll.setWidget(self.tab_host)
        self.tab_scroll.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        bv.addWidget(self.tab_scroll)

        # 右侧渐隐，提示这里还能横向滚动
        self.tab_fade = QWidget(self.body)
        self.tab_fade.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.tab_fade.setStyleSheet(
            "background:qlineargradient(spread:pad,x1:0,y1:0,x2:1,y2:0,"
            "stop:0 rgba(255,255,255,0),stop:1 rgba(255,255,255,255));")
        self.tab_fade.setVisible(False)
        self.tab_scroll.horizontalScrollBar().valueChanged.connect(self._update_fade)

        # 输入区
        iw = QWidget()
        il = QVBoxLayout(iw)
        il.setContentsMargins(14, 0, 14, 8)
        il.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_proj = QPushButton()
        self.btn_proj.setCursor(Qt.PointingHandCursor)
        self.btn_proj.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_proj.setStyleSheet(
            f"QPushButton{{border:none;background:{C_FILL};border-radius:9px;"
            f"padding:6px 12px;color:#5F7A70;font-size:9pt;text-align:left;}}"
            f"QPushButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")
        self.btn_proj.clicked.connect(self._pick_add_project)
        row.addWidget(self.btn_proj, 0)
        row.addStretch(1)

        self.btn_more = self._tool_btn("⋯", "更多")
        self.btn_more.clicked.connect(self._show_more_menu)
        row.addWidget(self.btn_more, 0)
        il.addLayout(row)

        self.input = QLineEdit()
        self.input.setPlaceholderText("记一件事，回车添加")
        self.input.setToolTip(
            "直接写日期就会自动带上截止日：\n"
            "「开会 明天」「交报告 11-06」「评审 3天后」\n"
            "要改已经记好的：双击那一行")
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self._on_add)
        self.input.setStyleSheet(
            f"QLineEdit{{background:#FFFFFF;border:1px solid #E4EFE9;"
            f"border-radius:11px;padding:9px 12px;color:{C_TEXT};"
            "selection-background-color:#BFEBD8;selection-color:#12402E;}"
            f"QLineEdit:focus{{border:1px solid {C_PRIMARY};background:#FDFFFE;}}")
        fi = QFont(self.input.font())
        fi.setPointSizeF(9.6)
        self.input.setFont(fi)

        # 截止日按钮紧贴输入框：明确它属于「要新记的这一条」
        in_row = QHBoxLayout()
        in_row.setSpacing(6)
        in_row.addWidget(self.input, 1)
        self.btn_due = QToolButton()
        self.btn_due.setCursor(Qt.PointingHandCursor)
        self.btn_due.setText("＋ 截止日")
        self.btn_due.setMinimumHeight(34)
        self.btn_due.setMinimumWidth(76)
        self.btn_due.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.btn_due.setToolTip(
            "给左边输入框里要新记的这一条定截止日。\n"
            "已经记好的事要改日期：双击那一行，或点它后面的日期小标签。\n"
            "也可以直接写：「开会 明天」「交报告 11-06」「评审 3天后」")
        self.btn_due.setStyleSheet(
            f"QToolButton{{border:1px solid {C_RING};background:#FFFFFF;"
            f"border-radius:11px;padding:0 10px;color:{C_PRIMARY_D};"
            "font-size:8.8pt;font-weight:600;}"
            f"QToolButton:hover{{border-color:{C_PRIMARY};background:{C_TINT};}}")
        self.btn_due.clicked.connect(self._pick_add_due)
        in_row.addWidget(self.btn_due, 0)
        il.addLayout(in_row)
        bv.addWidget(iw)

        # 列表
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}"
            "QScrollBar:vertical{width:6px;background:transparent;margin:0;}"
            "QScrollBar::handle:vertical{background:#D9E7E1;border-radius:3px;"
            "min-height:22px;}"
            "QScrollBar::handle:vertical:hover{background:#BFD6CB;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical"
            "{background:transparent;}")
        self.list_host = QWidget()
        self.list_host.setStyleSheet("background:transparent;")
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(12, 4, 8, 10)
        self.list_lay.setSpacing(0)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(self.list_host)
        bv.addWidget(self.scroll, 1)

        self.empty = EmptyView()
        self.empty.setVisible(False)
        bv.addWidget(self.empty, 1)

        # 底栏
        self.footer = QWidget()
        self.footer.setStyleSheet("background:transparent;")
        fv = QVBoxLayout(self.footer)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(0)

        bar_host = QWidget()
        bar_host.setStyleSheet("background:transparent;")
        bl = QHBoxLayout(bar_host)
        bl.setContentsMargins(16, 0, 16, 9)
        bl.setSpacing(0)
        self.pbar = ThinBar()
        bl.addWidget(self.pbar)

        row_w = QWidget()
        row_w.setStyleSheet("background:transparent;")
        fl = QHBoxLayout(row_w)
        fl.setContentsMargins(16, 7, 10, 3)
        fl.setSpacing(6)
        self.stat = QLabel("")
        self.stat.setStyleSheet(f"color:{C_SUB};font-size:8.4pt;background:transparent;")
        fl.addWidget(self.stat)
        fl.addStretch(1)
        self.b_done = self._tool_btn("隐藏已完成",
                                     "已完成的事会划线留在列表里；点这里收起或展开")
        self.b_done.setFixedSize(80, 24)
        self.b_done.setVisible(False)
        self.b_done.clicked.connect(self._toggle_show_done)
        fl.addWidget(self.b_done)
        fv.addWidget(row_w)
        fv.addWidget(bar_host)
        bv.addWidget(self.footer)

        v.addWidget(self.body, 1)

        self.grip = QSizeGrip(self.card)
        self.grip.setFixedSize(14, 14)
        self.grip.setStyleSheet("background:transparent;")
        self.grip.raise_()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_geometry)

        # 写盘失败必须当场告诉用户，否则买家用两天发现东西全没了
        self._err_timer = QTimer(self)
        self._err_timer.timeout.connect(self._flush_save_error)
        self._err_timer.start(2000)

        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("Escape"), self, activated=self._on_esc)

        self._refresh_header()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "grip") and self.grip:
            self.grip.move(self.card.width() - 16, self.card.height() - 16)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.move(max(10, (self.card.width() - self.toast.width()) // 2),
                            max(10, self.card.height() - self.toast.height() - 56))
        if hasattr(self, "_save_timer"):
            self._save_timer.start(700)
        self._update_fade()

    def _update_fade(self):
        if not hasattr(self, "tab_fade"):
            return
        bar = self.tab_scroll.horizontalScrollBar()
        can_scroll = bar.maximum() > 0
        at_end = bar.value() >= bar.maximum() - 1
        if can_scroll and not at_end:
            self.tab_fade.setGeometry(self.tab_scroll.x() + self.tab_scroll.width() - 28,
                                      self.tab_scroll.y(), 28,
                                      self.tab_scroll.height())
            self.tab_fade.raise_()
            self.tab_fade.setVisible(True)
        else:
            self.tab_fade.setVisible(False)

    def _say(self, msg, ms=2600):
        """底部浮出的小提示，不挡操作"""
        if not hasattr(self, "toast"):
            return
        self.toast.setText(msg)
        self.toast.adjustSize()
        c = self.card
        x = max(10, (c.width() - self.toast.width()) // 2)
        y = max(10, c.height() - self.toast.height() - 56)
        self.toast.move(x, y)
        self.toast.raise_()
        self.toast.setVisible(True)
        self._toast_timer.start(ms)

    def _tool_btn(self, text, tip=""):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(24, 24)
        b.setStyleSheet(
            f"QToolButton{{border:none;background:transparent;color:{C_SUB};"
            "border-radius:7px;font-size:9.5pt;}"
            f"QToolButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")
        return b

    # ---------------- 托盘 ----------------
    def _build_tray(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_PRIMARY))
        p.drawRoundedRect(QRectF(4, 4, 56, 56), 16, 16)
        pen = QPen(QColor("#FFFFFF"), 6)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPoint(20, 25), QPoint(29, 34))
        p.drawLine(QPoint(29, 34), QPoint(45, 17))
        p.end()

        self.tray = QSystemTrayIcon(QIcon(pm), self)
        self.tray.setToolTip(APP_NAME)
        m = QMenu()
        m.setStyleSheet(MENU_QSS)
        m.addAction("显示面板").triggered.connect(self._show_panel)
        m.addAction("快速记一笔…").triggered.connect(self._quick_add)
        m.addSeparator()
        m.addAction("退出").triggered.connect(self._quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_clicked)
        self.tray.show()

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_panel()

    def _show_panel(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def _hide_to_tray(self):
        self._save_geometry()
        self.hide()

    # ---------------- Tab ----------------
    def _build_tabs(self):
        while self.tab_lay.count() > 1:
            it = self.tab_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        counts = {}
        for t in self.store.tasks:
            if not t.get("done"):
                counts[t.get("pid", "")] = counts.get(t.get("pid", ""), 0) + 1

        tabs = [("all", "全部", "", counts.get("", 0) + sum(
            v for k, v in counts.items() if k))]
        for p in self.store.projects:
            tabs.append((p["id"], p["name"], p["color"], counts.get(p["id"], 0)))
        if counts.get("", 0):
            tabs.append(("", "未分类", C_SUB, counts.get("", 0)))

        for pid, name, color, n in tabs:
            btn = self._make_tab(pid, name, color, n)
            self.tab_lay.insertWidget(self.tab_lay.count() - 1, btn)

        add = QToolButton()
        add.setText("＋")
        add.setCursor(Qt.PointingHandCursor)
        add.setFixedSize(24, 24)
        add.setToolTip("新建项目")
        add.setStyleSheet(
            f"QToolButton{{border:1px dashed #CFE3DA;background:transparent;"
            f"color:{C_SUB};border-radius:13px;font-size:11pt;}}"
            f"QToolButton:hover{{border-color:{C_PRIMARY};color:{C_PRIMARY};"
            f"background:{C_TINT};}}")
        add.clicked.connect(self._new_project)
        self.tab_lay.insertWidget(self.tab_lay.count() - 1, add)

        # 逐个按钮累加宽度（不依赖 layout 的 sizeHint 缓存，切视图时才算得准）
        need_w = 0
        n = 0
        for i in range(self.tab_lay.count()):
            it = self.tab_lay.itemAt(i)
            w = it.widget()
            if w:
                need_w += w.sizeHint().width()
                n += 1
        if n:
            need_w += self.tab_lay.spacing() * (n - 1)
        need_w += self.tab_lay.contentsMargins().left() + \
            self.tab_lay.contentsMargins().right()
        self.tab_host.setFixedSize(max(need_w, 60), 28)
        QTimer.singleShot(0, self._update_fade)

    def _make_tab(self, pid, name, color, n):
        btn = QToolButton()
        btn.setCheckable(True)
        btn.setChecked(self._filter == pid)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setProperty("pid", pid)
        label = f"● {name}" if color else name
        btn.setText(f"{label} {n}" if n else label)
        dot_color = color or C_SUB
        if self._filter == pid:
            btn.setStyleSheet(
                f"QToolButton{{border:none;background:{C_PRIMARY};color:#fff;"
                "border-radius:10px;padding:4px 11px;font-size:8.8pt;font-weight:600;}"
                f"QToolButton:hover{{background:{C_PRIMARY_D};}}")
        else:
            btn.setStyleSheet(
                f"QToolButton{{border:none;background:{C_FILL};color:{dot_color};"
                "border-radius:10px;padding:4px 11px;font-size:8.8pt;}"
                f"QToolButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")
        btn.clicked.connect(lambda _, k=pid: self._set_filter(k))
        if pid not in ("all", ""):
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.setToolTip("右键：重命名 / 删除项目")
            btn.customContextMenuRequested.connect(
                lambda _, k=pid: self._project_menu(k))
        return btn

    def _set_filter(self, pid):
        self._filter = pid
        self.store.settings["filter"] = pid
        self.store.save()
        self._sync_add_pid()
        self.reload()

    def _sync_add_pid(self):
        # 当前 tab 是具体项目时，新任务默认归到它
        if self._filter not in ("all", ""):
            self._add_pid = self._filter
        elif self._filter == "all" and self._add_pid not in [p["id"] for p in self.store.projects]:
            self._add_pid = ""

    # ---------------- 渲染列表 ----------------
    def reload(self, focus_id=None):
        while self.list_lay.count() > 1:
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        self._build_tabs()
        self._sync_add_pid()

        tasks = self.store.tasks
        if self._filter == "all":
            scope = tasks
        else:
            scope = [t for t in tasks if t.get("pid", "") == self._filter]

        todo = [t for t in scope if not t.get("done")]
        done = [t for t in scope if t.get("done")]

        def key_todo(t):
            star = 0 if t.get("star") else 1
            due = t.get("due") or "9999-12-31"
            return (star, due, t.get("created", ""))

        todo.sort(key=key_todo)
        done.sort(key=lambda t: t.get("done_at") or "", reverse=True)

        shown = todo + (done if self._show_done else [])
        show_proj = self._filter == "all"
        focus_row = None
        prev_done = False
        for t in shown:
            cur_done = bool(t.get("done"))
            if cur_done and not prev_done:
                holder = QWidget()
                holder.setStyleSheet("background:transparent;")
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(6, 12, 8, 6)
                hl.setSpacing(8)
                tag = QLabel("已完成")
                ft = QFont(tag.font())
                ft.setPointSizeF(8.2)
                tag.setFont(ft)
                tag.setStyleSheet(f"color:#9AB0A7;background:transparent;")
                hl.addWidget(tag, 0)
                line = QFrame()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background:{C_LINE};border:none;")
                hl.addWidget(line, 1)
                self.list_lay.insertWidget(self.list_lay.count() - 1, holder)
            prev_done = cur_done

            row = TaskRow(t, self.store.project(t.get("pid", "")), show_proj)
            row.toggled.connect(self._on_toggle)
            row.deleted.connect(self._on_delete)
            row.edited.connect(self._on_edit)
            row.starToggled.connect(self._on_star)
            row.dueRequested.connect(self._on_set_due)
            row.editRequested.connect(self._on_edit_full)
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
            if focus_id and t.get("id") == focus_id:
                focus_row = row

        has = bool(shown)
        self.scroll.setVisible(has)
        self.empty.setVisible(not has)

        if not has:
            if not self.store.projects:
                self.empty.set_data("先建一个项目",
                                    "点上面的 ＋ 加一个，比如「配电网评审」")
            elif self._filter != "all" and not scope:
                self.empty.set_data("这里还空着",
                                    "在下面记一笔，写「开会 明天」会自动带上截止日")
            else:
                self.empty.set_data("都清空了，歇会儿", "新的事情随时记")

        n_todo = len(todo)
        n_done = len(done)
        overdue = sum(1 for t in todo
                      if t.get("due") and (dt.date.fromisoformat(t["due"])
                                           < dt.date.today()))
        stat = f"待办 {n_todo}"
        if overdue:
            stat += f" · 逾期 {overdue}"
        if n_done:
            stat += f" · 完成 {n_done}"
        self.stat.setText(stat)

        # 只有真的存在已完成项，才露出「隐藏/显示已完成」这个开关
        self.b_done.setVisible(bool(n_done))

        total = n_todo + n_done
        self.pbar.setValue((n_done / total) if total else 0.0)
        self.title.setText(f"{APP_NAME} · {n_todo}" if n_todo else APP_NAME)

        self._refresh_header()

        if focus_row is not None:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(focus_row, 0, 30))

    def _refresh_header(self):
        d = dt.date.today()
        self.date_lbl.setText(
            f"{d.month}月{d.day}日 {WEEK_CN[d.weekday()]} · {greeting()}")
        p = self.store.project(self._add_pid)
        self.btn_proj.setToolTip("新记的事情归到这个项目，点这里换")
        if p:
            self.btn_proj.setText(f"记到：{p['name']}  ▾")
            self.btn_proj.setStyleSheet(
                f"QPushButton{{border:none;background:{C_FILL};border-radius:9px;"
                f"padding:6px 12px;color:{p['color']};font-size:9pt;"
                "text-align:left;}"
                f"QPushButton:hover{{background:{C_TINT};}}")
        else:
            self.btn_proj.setText("记到：未分类  ▾")
            self.btn_proj.setStyleSheet(
                f"QPushButton{{border:none;background:{C_FILL};border-radius:9px;"
                "padding:6px 12px;color:#5F7A70;font-size:9pt;text-align:left;}"
                f"QPushButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")

        if self._add_due:
            label, state = due_info(self._add_due.isoformat())
            bg, fg = DUE_COLORS.get(state, DUE_COLORS["normal"])
            self.btn_due.setText(label)
            self.btn_due.setStyleSheet(
                f"QToolButton{{border:1px solid transparent;background:{bg};"
                f"border-radius:11px;padding:0 10px;color:{fg};"
                "font-size:8.8pt;font-weight:600;}"
                f"QToolButton:hover{{border-color:{C_PRIMARY};}}")
        else:
            self.btn_due.setText("＋ 截止日")
            self.btn_due.setStyleSheet(
                f"QToolButton{{border:1px solid {C_RING};background:#FFFFFF;"
                f"border-radius:11px;padding:0 10px;color:{C_PRIMARY_D};"
                "font-size:8.8pt;font-weight:600;}"
                f"QToolButton:hover{{border-color:{C_PRIMARY};background:{C_TINT};}}")

        self.b_done.setText("隐藏已完成" if self._show_done else "显示已完成")
        self.b_done.setToolTip(
            "已完成的事会划线留在列表里，点圆圈可以撤回"
            if self._show_done else "把划线的事重新显示出来")
        self.b_done.setStyleSheet(
            f"QToolButton{{border:none;background:"
            f"{'transparent' if not self._show_done else C_TINT};"
            f"color:{C_SUB if not self._show_done else C_PRIMARY_D};"
            "border-radius:7px;font-size:8.4pt;padding:0 2px;}"
            f"QToolButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")

        self.b_pin.setStyleSheet(
            f"QToolButton{{border:none;background:"
            f"{C_TINT if self.windowFlags() & Qt.WindowStaysOnTopHint else 'transparent'};"
            f"color:{C_PRIMARY_D if self.windowFlags() & Qt.WindowStaysOnTopHint else C_SUB};"
            "border-radius:7px;font-size:9.5pt;}"
            f"QToolButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")

        semi = self._opacity < 0.999
        self.b_op.setStyleSheet(
            f"QToolButton{{border:none;background:{C_TINT if semi else 'transparent'};"
            f"color:{C_PRIMARY_D if semi else C_SUB};"
            "border-radius:7px;font-size:9.5pt;}"
            f"QToolButton:hover{{background:{C_TINT};color:{C_PRIMARY_D};}}")

    # ---------------- 添加 ----------------
    def _on_add(self):
        raw = self.input.text().strip()
        if not raw:
            return
        text, d = parse_due(raw)
        if not text.strip():
            text, d = raw, None
        due = d.isoformat() if d else (self._add_due.isoformat() if self._add_due else None)
        star = False
        if text.startswith("!") or text.startswith("！"):
            star = True
            text = text[1:].strip()
        pid = self._add_pid if self.store.project(self._add_pid) else ""
        t = self.store.add(text, pid, due, star)
        self.input.clear()
        if t is None:                 # 只剩一个「!」之类，加进去是空条目
            self.input.setFocus()
            return
        self.reload(focus_id=t["id"])
        self.input.setFocus()

    def _on_esc(self):
        if self.input.text():
            self.input.clear()
        else:
            self._hide_to_tray()

    def _pick_add_project(self):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        acts = []
        for p in self.store.projects:
            a = menu.addAction("● " + p["name"])
            acts.append((a, p["id"], p["color"]))
        a_none = menu.addAction("● 未分类")
        menu.addSeparator()
        a_new = menu.addAction("＋ 新建项目…")
        act = menu.exec(self.btn_proj.mapToGlobal(QPoint(0, self.btn_proj.height() + 4)))
        if act is None:
            return
        if act == a_new:
            self._new_project()
            return
        if act == a_none:
            self._add_pid = ""
        else:
            for a, pid, _c in acts:
                if act == a:
                    self._add_pid = pid
                    break
        self._refresh_header()

    def _clamp_popup(self, dlg, px, py):
        """把弹出面板收进屏幕可见区，避免贴右边时被切掉"""
        dlg.adjustSize()
        w = max(dlg.size().width(), dlg.sizeHint().width())
        h = max(dlg.size().height(), dlg.sizeHint().height())
        scr = self.screen().availableGeometry()
        x = min(px, scr.right() - w - 8)
        y = min(py, scr.bottom() - h - 8)
        dlg.move(max(scr.left() + 8, x), max(scr.top() + 8, y))

    def _pick_add_due(self):
        dlg = DatePick(self._add_due, self)
        dlg.adjustSize()
        pw = max(dlg.size().width(), dlg.sizeHint().width())
        right = self.btn_due.mapToGlobal(
            QPoint(self.btn_due.width(), self.btn_due.height() + 4))
        self._clamp_popup(dlg, right.x() - pw, right.y())
        if dlg.exec() == QDialog.Accepted:
            self._add_due = dlg.result_date
            self._refresh_header()
            if self._add_due:
                self._say("新事项截止日：" +
                          due_info(self._add_due.isoformat())[0])
            else:
                self._say("已取消预设截止日")

    # ---------------- 操作 ----------------
    def _on_toggle(self, tid):
        t = self.store.get(tid)
        was_done = bool(t and t.get("done"))
        self.store.toggle(tid)
        if not was_done:
            # 划掉后一定要还能看见，否则用户会以为删了
            if not self._show_done:
                self._show_done = True
                self.store.settings["show_done"] = True
                self.store.save()
            self.reload(focus_id=tid)     # 滚到它现在的位置，看得见它在哪
            self._say("已完成，仍在下方「已完成」里 · 点圆圈可撤回")
        else:
            self.reload()
            self._say("已撤回，回到待办")

    def _on_delete(self, tid):
        self.store.remove(tid)
        self.reload()

    def _on_star(self, tid):
        t = self.store.get(tid)
        if t:
            self.store.update(tid, star=not t.get("star"))
        self.reload()

    def _on_edit(self, tid, text):
        if text == "|clear-due|":
            self.store.update(tid, due=None, notified=False)
        elif text.startswith("|move|"):
            self.store.update(tid, pid=text[6:])
        elif text:
            self.store.update(tid, text=text)
        self.reload()

    def _on_edit_full(self, tid):
        """双击任务：内容 + 截止日期一起改"""
        t = self.store.get(tid)
        if not t:
            return
        cur = None
        if t.get("due"):
            try:
                cur = dt.date.fromisoformat(t["due"])
            except Exception:
                cur = None
        text, nd = ask_task(self, "编辑事项", t.get("text", ""), cur)
        if text is None:
            return
        self.store.update(tid, text=text,
                          due=nd.isoformat() if nd else None,
                          notified=False)
        self.reload(focus_id=tid)
        self._say("已保存" if nd is None else
                  "已保存 · 截止 " + nd.strftime("%m-%d"))

    def _on_set_due(self, tid):
        t = self.store.get(tid)
        if not t:
            return
        cur = None
        if t.get("due"):
            try:
                cur = dt.date.fromisoformat(t["due"])
            except Exception:
                cur = None
        dlg = DatePick(cur, self)
        dlg.adjustSize()
        pw = max(dlg.size().width(), dlg.sizeHint().width())
        ph = max(dlg.size().height(), dlg.sizeHint().height())
        c = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        self._clamp_popup(dlg, c.x() - pw // 2, c.y() - ph // 2)
        if dlg.exec() == QDialog.Accepted:
            nd = dlg.result_date
            self.store.update(tid, due=nd.isoformat() if nd else None, notified=False)
            self.reload()
            self._say("截止日已更新为 " + (nd.strftime("%m-%d") if nd else "无"))

    # ---------------- 项目 ----------------
    def _new_project(self):
        name, ok = ask_text(self, "新建项目", "项目名称",
                            placeholder="比如：配电网评审")
        if not ok:
            return
        p = self.store.add_project(name)
        self._filter = p["id"]
        self._add_pid = p["id"]
        self.store.settings["filter"] = p["id"]
        self.store.save()
        self.reload()

    def _project_menu(self, pid):
        p = self.store.project(pid)
        if not p:
            return
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        a_ren = menu.addAction("重命名")
        a_del = menu.addAction("删除项目")
        act = menu.exec(QCursor.pos())
        if act == a_ren:
            name, ok = ask_text(self, "重命名项目", "项目名称", p["name"])
            if ok:
                self.store.rename_project(pid, name)
                self.reload()
        elif act == a_del:
            n = sum(1 for t in self.store.tasks if t.get("pid") == pid)
            msg = f"删除项目「{p['name']}」？"
            if n:
                msg += f"\n它下面的 {n} 条任务会变成「未分类」，不会丢。"
            if ask_confirm(self, "删除项目", msg, ok_text="删除"):
                self.store.delete_project(pid)
                if self._filter == pid:
                    self._filter = "all"
                    self.store.settings["filter"] = "all"
                    self.store.save()
                if self._add_pid == pid:
                    self._add_pid = ""
                self.reload()

    # ---------------- 其它 ----------------
    # ---------------- 透明度 ----------------
    def _show_opacity_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        head = menu.addAction("背景透明度")
        head.setEnabled(False)
        menu.addSeparator()
        acts = []
        for v, label in OPACITY_PRESETS:
            mark = "✓ " if abs(v - self._opacity) < 0.01 else "    "
            a = menu.addAction(mark + label)
            acts.append((a, v))
        menu.addSeparator()
        a_hover = menu.addAction(
            ("✓ " if self._hover_opaque else "    ") + "鼠标移入时变清晰")
        act = menu.exec(self.b_op.mapToGlobal(
            QPoint(0, self.b_op.height() + 4)))
        if act is None:
            return
        if act == a_hover:
            self._hover_opaque = not self._hover_opaque
            self.store.settings["hover_opaque"] = self._hover_opaque
            self.store.save()
            self._refresh_card()
            return
        for a, v in acts:
            if act == a:
                self._opacity = v
                self.store.settings["opacity"] = v
                self.store.save()
                self._refresh_card()
                self._refresh_header()
                return

    def _refresh_card(self):
        # 折叠态照样遵守「鼠标不在就半透明」，只是折叠条更矮，别让它一直
        # 实白地杵在桌面上。
        eff = 1.0 if (self._hover_opaque and getattr(self, "_hovering", False)) \
            else self._opacity
        if abs(eff - self._card_alpha) > 0.004:
            self._card_alpha = eff
            self.card.setStyleSheet(card_qss(eff))
            # 标签栏右端的渐隐也要跟着底板一起变透明
            if hasattr(self, "tab_fade"):
                self.tab_fade.setStyleSheet(
                    "background:qlineargradient(spread:pad,x1:0,y1:0,x2:1,y2:0,"
                    f"stop:0 rgba(255,255,255,0),"
                    f"stop:1 rgba(255,255,255,{min(1.0, eff):.3f}));")

    def _check_hover_opacity(self):
        if not self.isVisible():
            return
        self._hovering = self.frameGeometry().contains(QCursor.pos())
        if self._opacity < 0.999 or self._card_alpha != 1.0:
            self._refresh_card()

    def _toggle_on_top(self):
        on = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, not on)
        self.show()
        self.store.settings["on_top"] = not on
        self.store.save()
        self._refresh_header()

    def _toggle_show_done(self):
        self._show_done = not self._show_done
        self.store.settings["show_done"] = self._show_done
        self.store.save()
        self._refresh_header()
        self.reload()

    def _toggle_fold(self):
        self._folded = not self._folded
        self.store.settings["folded"] = self._folded
        self.store.save()
        self._apply_fold()

    def _set_card_shadow(self, on):
        """折叠态不要阴影。

        阴影是用 QGraphicsDropShadowEffect 实现的，它会把整个卡片先渲染进
        一张缓存位图再贴出来。窗口高度从 500 骤降到 84 时这张缓存位图的尺寸
        不一定跟着更新，卡片就成了空白（阴影还在、文字没了）。折叠态本来也
        不需要 34px 的大阴影，直接摘掉最省事。
        """
        if self.card.graphicsEffect() is not None:
            self.card.setGraphicsEffect(None)
        if not on:
            return
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(34)
        sh.setOffset(0, 8)
        sh.setColor(QColor(18, 58, 44, 42))
        self.card.setGraphicsEffect(sh)

    def _kick_repaint(self):
        self.card.updateGeometry()
        self.card.update()
        self.update()

    def _apply_fold(self):
        self.body.setVisible(not self._folded)
        self.b_fold.setText("▢" if self._folded else "—")
        visible = self.isVisible()
        if visible:
            self.setUpdatesEnabled(False)
        if self._folded:
            # 折叠后的高度 = 标题栏 + 卡片上下留白。必须同步压低「最小高度」，
            # 否则 resize 会被 minimumSize 顶回去，标题栏下面空出一大片白底。
            # 最大高度也要锁死，避免折叠态被拖大后又是一片空白。
            self.setMinimumHeight(FOLD_H)
            self.setMaximumHeight(FOLD_H)
            self.card.setMinimumHeight(FOLD_H - CARD_MARGIN * 2)
            self.grip.setVisible(False)
            self.resize(self.width(), FOLD_H)
        else:
            self.setMinimumHeight(MIN_OPEN_H)
            self.setMaximumHeight(16777215)      # QWIDGETSIZE_MAX，解除折叠时的锁
            self.card.setMinimumHeight(220)
            self.grip.setVisible(True)
            self.resize(self.width(),
                        max(MIN_OPEN_H, int(self.store.settings.get("h") or 500)))
        # 展开才要阴影；折叠态摘掉（见 _set_card_shadow 的说明）
        self._set_card_shadow(not self._folded)
        # 折叠/展开两态的底板不透明度规则不同（见 _refresh_card），要立刻生效
        self._card_alpha = -1.0
        self._refresh_card()
        if visible:
            self.setUpdatesEnabled(True)
            # 高度骤变后，半透明无边框窗口在 Windows 上会丢掉原来的合成表面，
            # 只补画「变化了」的那几块，剩下全是白底——折叠时就是一整块白板。
            # update()/repaint() 改不动合成层，hide + show 会让窗口重建一次
            # 合成表面，内容才会完整重画。两者在同一函数里，不会看到闪。
            self.hide()
            self.show()
            QTimer.singleShot(0, self._kick_repaint)


    def _show_more_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS)
        a1 = menu.addAction("清空当前视图的已完成")
        a2 = menu.addAction("打开数据文件夹")
        a3 = menu.addAction("新建项目…")
        a4 = menu.addAction("置顶显示" + ("  ✓" if self.windowFlags()
                                          & Qt.WindowStaysOnTopHint else ""))
        menu.addSeparator()
        a5 = menu.addAction("退出")
        act = menu.exec(self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 2)))
        if act == a1:
            self.store.clear_done(None if self._filter == "all" else self._filter)
            self.reload()
        elif act == a2:
            # 打开文件夹而不是文件：新装还没写过盘时文件不存在，
            # 直接 startfile 一个不存在的路径会报错
            try:
                DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
                os.startfile(str(DATA_PATH.parent))
            except Exception as e:
                self._say("打不开文件夹：" + str(e))
        elif act == a3:
            self._new_project()
        elif act == a4:
            self._toggle_on_top()
        elif act == a5:
            self._quit()

    def _quick_add(self):
        s, ok = ask_text(self, "快速记一笔", "内容",
                         placeholder="比如：出对比图 明天")
        if ok:
            text, d = parse_due(s)
            if text.strip():
                self.store.add(text, self._add_pid if self.store.project(self._add_pid) else "",
                               d.isoformat() if d else None, False)
                self.reload()

    def _check_reminders(self):
        now = dt.datetime.now()
        fired = []
        for t in self.store.tasks:
            if t.get("done") or not t.get("due") or t.get("notified"):
                continue
            try:
                d = dt.date.fromisoformat(t["due"])
            except Exception:
                continue
            # 只在到期当天上午 9 点后提醒一次；逾期的不反复弹，靠界面红色标出
            if d == dt.date.today() and now.hour >= 9:
                t["notified"] = True
                fired.append(t)
        if fired:
            self.store.save()
            names = "\n".join("· " + t["text"] for t in fired[:4])
            if len(fired) > 4:
                names += f"\n… 还有 {len(fired) - 4} 项"
            self.tray.showMessage(f"{APP_NAME} · 有 {len(fired)} 项到期",
                                  names, QSystemTrayIcon.Information, 8000)
            QApplication.beep()
            try:
                import winsound
                winsound.MessageBeep(0x00000040)
            except Exception:
                pass
            self.reload()

    def _on_day_tick(self):
        today = dt.date.today()
        if today != self._today:
            self._today = today
            self._refresh_header()
            self.reload()

    def _flush_save_error(self):
        """写盘失败的提示，只弹一次。"""
        err = self._pending_save_error
        if not err:
            return
        self._pending_save_error = None
        path, msg = err
        self._say("保存失败，请检查文件夹权限")
        try:
            ask_confirm(self, "数据没能保存",
                        f"写入下面这个位置时出错：\n{path}\n\n{msg}\n\n"
                        "请把程序换到有写入权限的文件夹（比如 D 盘自建目录），"
                        "或者先把 data.json 复制一份备份。",
                        ok_text="知道了", danger=True, width=390)
        except Exception:
            pass

    def _quit(self):
        self.store.save()
        self.tray.hide()
        QApplication.quit()

    # ---------------- 位置 ----------------
    def _restore_pos(self):
        st = self.store.settings
        x, y = st.get("x"), st.get("y")
        scr = QGuiApplication.primaryScreen().availableGeometry()
        if x is None or y is None:
            self.move(scr.right() - self.width() - 40, scr.top() + 80)
        else:
            x = max(scr.left() - self.width() + 60, min(int(x), scr.right() - 60))
            y = max(scr.top(), min(int(y), scr.bottom() - 40))
            self.move(int(x), int(y))

    def _save_geometry(self):
        st = self.store.settings
        scr = QGuiApplication.primaryScreen().availableGeometry()
        x = max(scr.left() - self.width() + 60, min(self.x(), scr.right() - 60))
        y = max(scr.top(), min(self.y(), scr.bottom() - 40))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
        st["x"], st["y"] = self.x(), self.y()
        if not self._folded:
            st["h"] = self.height()
        st["w"] = self.width()
        self.store.save()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            pt = self.card.mapFromGlobal(e.globalPosition().toPoint())
            if self.header.geometry().contains(pt):
                self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.header.setCursor(Qt.ClosedHandCursor)
                e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self._drag_pos = None
            self.header.setCursor(Qt.OpenHandCursor)
            self._save_geometry()

    def closeEvent(self, e):
        e.ignore()
        self._save_geometry()
        self.hide()


# ============================================================
IPC_NAME = "TodayPlan-SingleInstance-v2"


def activate_existing():
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def _install_crash_log():
    """把未捕获异常写进日志。

    打包成 --windowed 后没有控制台，print 出来的东西谁也看不见。
    买家说"它自己闪退了"时，有这个日志才能查。
    """
    log = LOG_DIR / "error.log"

    def hook(exc_type, exc, tb):
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write("\n" + "=" * 60 + "\n")
                fh.write(dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
                fh.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = hook


def main():
    _install_crash_log()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)

    if activate_existing():
        return

    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(IPC_NAME)
    server = QLocalServer()
    server.listen(IPC_NAME)

    f = QFont("Microsoft YaHei UI")
    f.setPointSizeF(9.5)
    app.setFont(f)

    w = Planner()

    def on_new_conn():
        while server.hasPendingConnections():
            c = server.nextPendingConnection()
            c.readyRead.connect(lambda: c.readAll())
            c.disconnected.connect(c.deleteLater)
        w._show_panel()

    server.newConnection.connect(on_new_conn)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
