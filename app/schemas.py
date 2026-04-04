from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, Any
from datetime import date, datetime
from enum import Enum


# ── Auth ──────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class KategoriUmkm(str, Enum):
    kuliner  = "Kuliner"
    fashion  = "Fashion"
    kerajinan = "Kerajinan"
    lainnya  = "Lainnya"


# ── Stok ──────────────────────────────────────────────────────

class KategoriBarang(str, Enum):
    makanan   = "Makanan"
    minuman   = "Minuman"
    camilan   = "Camilan"
    fashion   = "Fashion"
    kerajinan = "Kerajinan"
    lainnya   = "Lainnya"


class CreateBarangRequest(BaseModel):
    nama: str
    stok: int
    harga: int
    kategori: Optional[KategoriBarang] = None
    satuan: Optional[str] = None
    deskripsi: Optional[str] = None
    max: Optional[int] = 100  # maps to stok_max

    @field_validator("stok", "harga")
    @classmethod
    def non_negative(cls, v):
        if v < 0:
            raise ValueError("Nilai tidak boleh negatif")
        return v


class UpdateBarangRequest(BaseModel):
    nama: Optional[str] = None
    stok: Optional[int] = None
    harga: Optional[int] = None
    kategori: Optional[KategoriBarang] = None
    satuan: Optional[str] = None
    deskripsi: Optional[str] = None
    max: Optional[int] = None  # maps to stok_max


# ── Kas ───────────────────────────────────────────────────────

class JenisKas(str, Enum):
    masuk  = "masuk"
    keluar = "keluar"


class CreateKasRequest(BaseModel):
    tgl: date
    ket: str
    jenis: JenisKas
    nominal: int
    kategori: Optional[str] = None

    @field_validator("nominal")
    @classmethod
    def positive_nominal(cls, v):
        if v <= 0:
            raise ValueError("Nominal harus lebih dari 0")
        return v


class UpdateKasRequest(BaseModel):
    tgl: Optional[date] = None
    ket: Optional[str] = None
    jenis: Optional[JenisKas] = None
    nominal: Optional[int] = None
    kategori: Optional[str] = None


# ── Promo ─────────────────────────────────────────────────────

class TipePromo(str, Enum):
    persentase    = "Persentase"
    nominal       = "Nominal"
    beli_gratis   = "BeliXGratisY"
    gratis_ongkir = "GratisOngkir"
    lainnya       = "Lainnya"


class StatusPromo(str, Enum):
    aktif    = "aktif"
    nonaktif = "nonaktif"


# ── Profil ────────────────────────────────────────────────────

class UpdateProfilRequest(BaseModel):
    nama_pemilik: Optional[str] = None
    nama_usaha: Optional[str] = None
    alamat: Optional[str] = None
    kategori: Optional[KategoriUmkm] = None
    deskripsi: Optional[str] = None


class GantiPasswordRequest(BaseModel):
    password_lama: str
    password_baru: str
    konfirmasi_password: str

    @field_validator("password_baru")
    @classmethod
    def min_length(cls, v):
        if len(v) < 6:
            raise ValueError("Password baru minimal 6 karakter")
        return v
