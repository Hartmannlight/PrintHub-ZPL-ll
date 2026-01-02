from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

QrEcc = Literal['L', 'M', 'Q', 'H']
QrMode = Literal['numeric', 'alphanumeric', 'byte']


@dataclass(frozen=True)
class InkMetricsDots:
    ink_offset_x: int
    ink_offset_y: int
    ink_width: int
    ink_height: int

    @property
    def ink_left(self) -> int:
        return self.ink_offset_x

    @property
    def ink_top(self) -> int:
        return self.ink_offset_y

    @property
    def ink_right(self) -> int:
        return self.ink_offset_x + self.ink_width

    @property
    def ink_bottom(self) -> int:
        return self.ink_offset_y + self.ink_height

    @property
    def ink_center_x(self) -> float:
        return self.ink_offset_x + (self.ink_width / 2.0)

    @property
    def ink_center_y(self) -> float:
        return self.ink_offset_y + (self.ink_height / 2.0)


@dataclass(frozen=True)
class SymbolSizeDots:
    symbol_width: int
    symbol_height: int
    recommended_width: int
    recommended_height: int


@dataclass(frozen=True)
class ZplSymbol:
    zpl: str
    size_dots: SymbolSizeDots
    ink: InkMetricsDots
    kind: Literal['qr', 'datamatrix']
    meta: dict[str, object]


_QR_CAPACITY_CODEWORDS_LMQH: list[tuple[int, int, int, int]] = [
    (19, 16, 13, 9), (34, 28, 22, 16), (55, 44, 34, 26), (80, 64, 48, 36),
    (108, 86, 62, 46), (136, 108, 76, 60), (156, 124, 88, 66), (194, 154, 110, 86),
    (232, 182, 132, 100), (274, 216, 154, 122), (324, 254, 180, 140), (370, 290, 206, 158),
    (428, 334, 244, 180), (461, 365, 261, 197), (523, 415, 295, 223), (589, 453, 325, 253),
    (647, 507, 367, 283), (721, 563, 397, 313), (795, 627, 445, 341), (861, 669, 485, 385),
    (932, 714, 512, 406), (1006, 782, 568, 442), (1094, 860, 614, 464), (1174, 914, 664, 514),
    (1276, 1000, 718, 538), (1370, 1062, 754, 596), (1468, 1128, 808, 628), (1531, 1193, 871, 661),
    (1631, 1267, 911, 701), (1735, 1373, 985, 745), (1843, 1455, 1033, 793), (1955, 1541, 1115, 845),
    (2071, 1631, 1171, 901), (2191, 1725, 1231, 961), (2306, 1812, 1286, 986), (2434, 1914, 1354, 1054),
    (2566, 1992, 1426, 1096), (2702, 2102, 1502, 1142), (2812, 2216, 1582, 1222), (2956, 2334, 1666, 1276),
]

_QR_FORCED_TOP_MODULES = 5


def _qr_ecc_index(ecc: QrEcc) -> int:
    return {'L': 0, 'M': 1, 'Q': 2, 'H': 3}[ecc]


_QR_ALPHANUM_SET = set('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:')


def _qr_mode_for_data(data: str | bytes) -> QrMode:
    if isinstance(data, bytes):
        return 'byte'
    if data.isdigit():
        return 'numeric'
    if all(ch in _QR_ALPHANUM_SET for ch in data):
        return 'alphanumeric'
    return 'byte'


def _qr_length_bits(mode: QrMode, version: int) -> int:
    if mode == 'numeric':
        return 10 if version < 10 else 12 if version < 27 else 14
    if mode == 'alphanumeric':
        return 9 if version < 10 else 11 if version < 27 else 13
    return 8 if version < 10 else 16


def _qr_data_bits(mode: QrMode, length: int) -> int:
    if mode == 'numeric':
        whole, rem = divmod(length, 3)
        return whole * 10 + (4 if rem == 1 else 7 if rem == 2 else 0)
    if mode == 'alphanumeric':
        whole, rem = divmod(length, 2)
        return whole * 11 + (6 if rem == 1 else 0)
    return length * 8


def _qr_required_bits(mode: QrMode, length: int, version: int) -> int:
    return 4 + _qr_length_bits(mode, version) + _qr_data_bits(mode, length)


def _qr_select_version_for_data(data: str | bytes, ecc: QrEcc) -> tuple[int, QrMode]:
    length = len(data)
    if length < 0:
        raise ValueError('data length must be >= 0')

    mode = _qr_mode_for_data(data)
    for version in range(1, 41):
        data_bits = _QR_CAPACITY_CODEWORDS_LMQH[version - 1][_qr_ecc_index(ecc)] * 8
        if _qr_required_bits(mode, length, version) <= data_bits:
            return version, mode
    raise ValueError(f'Data too large for QR (len={length}, ecc={ecc}, mode={mode})')


def _qr_modules_per_side(version: int) -> int:
    return 4 * version + 17


class QrCodeZplBuilder:
    def __init__(
        self,
        magnification: int,
        ecc: QrEcc = 'M',
        model: int = 2,
        orientation: Literal['N', 'R', 'I', 'B'] = 'N',
        quiet_zone_modules_recommended: int = 4,
        ink_offset_x_dots: int = 0,
        ink_offset_y_dots: int = 0,
    ) -> None:
        if not (1 <= magnification <= 10):
            raise ValueError('magnification must be in [1..10]')
        if model not in (1, 2):
            raise ValueError('model must be 1 or 2')
        if orientation not in ('N', 'R', 'I', 'B'):
            raise ValueError('orientation must be one of N, R, I, B')
        if quiet_zone_modules_recommended < 0:
            raise ValueError('quiet_zone_modules_recommended must be >= 0')
        if ink_offset_x_dots < 0 or ink_offset_y_dots < 0:
            raise ValueError('ink_offset_x_dots/ink_offset_y_dots must be >= 0')

        self._mag = magnification
        self._ecc = ecc
        self._model = model
        self._ori = orientation
        self._qz_rec = quiet_zone_modules_recommended
        self._ink_off_x = ink_offset_x_dots
        self._ink_off_y = ink_offset_y_dots

    def build(self, data: str | bytes, x: int = 0, y: int = 0) -> ZplSymbol:
        data_bytes = data if isinstance(data, bytes) else data.encode('ascii')
        if len(data_bytes) > 9999:
            raise ValueError('ZPL QR byte-mode length (Bxxxx) supports up to 9999 bytes')

        version, mode = _qr_select_version_for_data(data if isinstance(data, str) else data_bytes, self._ecc)
        modules = _qr_modules_per_side(version)

        ink_w = modules * self._mag
        ink_h = modules * self._mag

        forced_top = _QR_FORCED_TOP_MODULES * self._mag
        symbol_w = ink_w
        symbol_h = ink_h + forced_top

        qz_dots_rec = self._qz_rec * self._mag
        rec_w = symbol_w + 2 * qz_dots_rec
        rec_h = symbol_h + 2 * qz_dots_rec

        bcd_len = f'{len(data_bytes):04d}'
        payload = data_bytes.decode('ascii')

        zpl = (
            '^XA\n'
            f'^FO{x},{y}^BQ{self._ori},{self._model},{self._mag}\n'
            f'^FD{self._ecc}M,B{bcd_len}{payload}^FS\n'
            '^XZ'
        )

        return ZplSymbol(
            zpl=zpl,
            size_dots=SymbolSizeDots(
                symbol_width=symbol_w,
                symbol_height=symbol_h,
                recommended_width=rec_w,
                recommended_height=rec_h,
            ),
            ink=InkMetricsDots(
                ink_offset_x=self._ink_off_x,
                ink_offset_y=self._ink_off_y + forced_top,
                ink_width=ink_w,
                ink_height=ink_h,
            ),
            kind='qr',
            meta={
                'version': version,
                'modules': modules,
                'magnification': self._mag,
                'ecc': self._ecc,
                'mode': mode,
                'orientation': self._ori,
                'quiet_zone_modules_recommended': self._qz_rec,
                'quiet_zone_dots_recommended': qz_dots_rec,
                'forced_top_modules': _QR_FORCED_TOP_MODULES,
                'forced_top_dots': forced_top,
                'ink_offset_x_dots': self._ink_off_x,
                'ink_offset_y_dots': self._ink_off_y + forced_top,
            },
        )


class DataMatrixZplBuilder:
    def __init__(
        self,
        module_size: int,
        columns: int,
        rows: int,
        quality: int = 200,
        escape_char: str = '_',
        quiet_zone_modules_recommended: int = 1,
        ink_offset_x_dots: int = 0,
        ink_offset_y_dots: int = 0,
    ) -> None:
        if module_size <= 0:
            raise ValueError('module_size must be > 0')
        if quality != 200:
            raise ValueError('This builder targets ECC200 (quality=200) only')
        if columns <= 0 or rows <= 0:
            raise ValueError('columns/rows must be > 0')
        if len(escape_char) != 1:
            raise ValueError('escape_char must be a single character')
        if quiet_zone_modules_recommended < 0:
            raise ValueError('quiet_zone_modules_recommended must be >= 0')
        if ink_offset_x_dots < 0 or ink_offset_y_dots < 0:
            raise ValueError('ink_offset_x_dots/ink_offset_y_dots must be >= 0')

        self._h = module_size
        self._c = columns
        self._r = rows
        self._q = quality
        self._esc = escape_char
        self._qz_rec = quiet_zone_modules_recommended
        self._ink_off_x = ink_offset_x_dots
        self._ink_off_y = ink_offset_y_dots

    def build(self, data: str | bytes, x: int = 0, y: int = 0) -> ZplSymbol:
        payload = data.decode('ascii') if isinstance(data, bytes) else data
        if self._esc in payload:
            raise ValueError(
                f'Data contains escape_char={self._esc!r}. Choose a different escape_char.'
            )

        ink_w = self._c * self._h
        ink_h = self._r * self._h

        qz_dots_rec = self._qz_rec * self._h
        rec_w = ink_w + 2 * qz_dots_rec
        rec_h = ink_h + 2 * qz_dots_rec

        zpl = (
            '^XA\n'
            f'^FO{x},{y}^BXN,{self._h},{self._q},{self._c},{self._r},6,{self._esc}\n'
            f'^FD{payload}^FS\n'
            '^XZ'
        )

        return ZplSymbol(
            zpl=zpl,
            size_dots=SymbolSizeDots(
                symbol_width=ink_w,
                symbol_height=ink_h,
                recommended_width=rec_w,
                recommended_height=rec_h,
            ),
            ink=InkMetricsDots(
                ink_offset_x=self._ink_off_x,
                ink_offset_y=self._ink_off_y,
                ink_width=ink_w,
                ink_height=ink_h,
            ),
            kind='datamatrix',
            meta={
                'columns': self._c,
                'rows': self._r,
                'module_size': self._h,
                'quality': self._q,
                'escape_char': self._esc,
                'quiet_zone_modules_recommended': self._qz_rec,
                'quiet_zone_dots_recommended': qz_dots_rec,
                'ink_offset_x_dots': self._ink_off_x,
                'ink_offset_y_dots': self._ink_off_y,
            },
        )
