-- ============================================================
-- SUPABASE SCHEMA — Sistem UMKM Peken Banyumas
-- Versi 1.0 | Database TERPISAH dari Gate
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── UMKM (Pemilik Kios) ──────────────────────────────────────
CREATE TABLE umkm (
    id                  UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    nama_pemilik        VARCHAR(100) NOT NULL,
    email               VARCHAR(100) NOT NULL UNIQUE,
    password_hash       VARCHAR(255) NOT NULL,
    nama_usaha          VARCHAR(150) NOT NULL,
    alamat              TEXT,
    kategori            VARCHAR(50),
    deskripsi           TEXT,
    nomor_stand         VARCHAR(10),
    zona                VARCHAR(50),
    status_pendaftaran  VARCHAR(20)  NOT NULL DEFAULT 'pending',
    file_ktp_url        TEXT,
    file_nib_url        TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_status_pendaftaran
        CHECK (status_pendaftaran IN ('pending', 'approved', 'rejected'))
);

COMMENT ON TABLE umkm IS 'Pemilik kios UMKM. Registrasi → pending → approved/rejected oleh admin gate.';
COMMENT ON COLUMN umkm.nomor_stand IS 'Misal: A-12, B-03. Unik per event, tidak dipaksa UNIQUE di DB karena bisa ganti event.';

-- ── BARANG (Stok per Kios) ───────────────────────────────────
CREATE TABLE barang (
    id          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    umkm_id     UUID         NOT NULL REFERENCES umkm(id) ON DELETE CASCADE,
    nama        VARCHAR(150) NOT NULL,
    stok        INTEGER      NOT NULL DEFAULT 0 CHECK (stok >= 0),
    stok_max    INTEGER      NOT NULL DEFAULT 100 CHECK (stok_max > 0),
    harga       INTEGER      NOT NULL DEFAULT 0 CHECK (harga >= 0),
    kategori    VARCHAR(50),
    satuan      VARCHAR(20),
    deskripsi   TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN barang.stok_max IS 'Kapasitas stok maks untuk progress bar di frontend.';

-- ── KAS (Buku Kas per Kios) ──────────────────────────────────
CREATE TABLE kas (
    id          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    umkm_id     UUID         NOT NULL REFERENCES umkm(id) ON DELETE CASCADE,
    tgl         DATE         NOT NULL,
    ket         VARCHAR(255) NOT NULL,
    jenis       VARCHAR(10)  NOT NULL CHECK (jenis IN ('masuk', 'keluar')),
    nominal     INTEGER      NOT NULL CHECK (nominal > 0),
    kategori    VARCHAR(50),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── PROMO (Diskon per Kios) ──────────────────────────────────
CREATE TABLE promo (
    id          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    umkm_id     UUID         NOT NULL REFERENCES umkm(id) ON DELETE CASCADE,
    nama        VARCHAR(150) NOT NULL,
    tipe        VARCHAR(50)  NOT NULL,
    nilai       VARCHAR(50)  NOT NULL,
    mulai       DATE         NOT NULL,
    akhir       DATE         NOT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'aktif'
                             CHECK (status IN ('aktif', 'nonaktif')),
    poster_url  TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_tanggal_promo CHECK (akhir >= mulai)
);

COMMENT ON COLUMN promo.nilai IS 'Nilai promo sesuai tipe: "20%" | "10000" | "B2G1" | dll.';
COMMENT ON COLUMN promo.tipe  IS 'Persentase | Nominal | BeliXGratisY | GratisOngkir | Lainnya';

-- ── TRANSAKSI (Riwayat Penjualan) ────────────────────────────
CREATE TABLE transaksi (
    id          BIGSERIAL    PRIMARY KEY,
    umkm_id     UUID         NOT NULL REFERENCES umkm(id) ON DELETE CASCADE,
    customer    VARCHAR(100),
    item        TEXT,
    total       INTEGER      NOT NULL DEFAULT 0 CHECK (total >= 0),
    waktu       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    status      VARCHAR(20)  NOT NULL DEFAULT 'Selesai'
                             CHECK (status IN ('Selesai', 'Proses')),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── NOTIFIKASI ───────────────────────────────────────────────
CREATE TABLE notifikasi (
    id          UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    umkm_id     UUID         NOT NULL REFERENCES umkm(id) ON DELETE CASCADE,
    title       VARCHAR(255) NOT NULL,
    deskripsi   TEXT,
    type        VARCHAR(20)  NOT NULL CHECK (type IN ('stok', 'transaksi', 'promo', 'info')),
    read        BOOLEAN      NOT NULL DEFAULT FALSE,
    detail      JSONB,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── INDEXES ──────────────────────────────────────────────────
CREATE INDEX idx_umkm_status        ON umkm(status_pendaftaran);
CREATE INDEX idx_barang_umkm        ON barang(umkm_id);
CREATE INDEX idx_kas_umkm           ON kas(umkm_id);
CREATE INDEX idx_kas_tgl            ON kas(tgl);
CREATE INDEX idx_promo_umkm         ON promo(umkm_id);
CREATE INDEX idx_promo_status       ON promo(status);
CREATE INDEX idx_promo_akhir        ON promo(akhir);
CREATE INDEX idx_transaksi_umkm     ON transaksi(umkm_id);
CREATE INDEX idx_transaksi_waktu    ON transaksi(waktu);
CREATE INDEX idx_notifikasi_umkm    ON notifikasi(umkm_id);
CREATE INDEX idx_notifikasi_read    ON notifikasi(read);

-- ── STORAGE BUCKETS (jalankan via Supabase Dashboard) ────────
-- INSERT INTO storage.buckets (id, name, public) VALUES ('dokumen-umkm', 'dokumen-umkm', false);
-- INSERT INTO storage.buckets (id, name, public) VALUES ('poster-promo', 'poster-promo', true);
