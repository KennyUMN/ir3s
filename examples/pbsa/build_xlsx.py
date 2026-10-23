"""PT Paramita Bangun Sarana Tbk (PBSA) 2019-2025, newest report per year.

    .venv/bin/python examples/pbsa/build_xlsx.py [out.xlsx]

Some printed labels run into the line before or after them (the 2020 report
prefixes "Liabilitas sewa - yang jatuh ..." to the lines below the lease
line), so the patterns are not anchored where that happens, and within a part
the first unused rule that matches wins.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from statements_xlsx import build  # noqa: E402

# The December reports from www.paramita.co.id/fin-statement.php, saved as
# pbsa_fs_<year>.pdf.
PDF_DIR = os.environ.get("PBSA_PDF_DIR", os.path.expanduser("~/.hermes/cache/scratch/audit/prda"))
PDF = os.path.join(PDF_DIR, "pbsa_fs_{}.pdf")
OUT = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "PBSA_2019_2025.xlsx")
YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
REPORTS = [2025, 2024, 2023, 2022, 2021, 2020]  # newest first: a restated figure wins

BS = [
    ("ca.cash", "Kas dan setara kas / Cash and cash equivalents", 0, "ca", r"Kas dan setara kas"),
    ("ca.restricted", "Deposito berjangka yang dibatasi penggunaannya / Restricted time deposits", 0, "ca", r"^Deposito berjangka yang dibatasi"),
    ("ca.sti", "Investasi jangka pendek / Short-term investments", 0, "ca", r"^Investasi jangka pendek"),
    ("ca.ar", "Piutang usaha - neto / Trade receivables - net", 0, "ca", r"^Piutang usaha"),
    ("ca.gross", "Tagihan bruto kepada pemberi kerja / Gross amount due from customers", 0, "ca", r"^Tagihan bruto"),
    ("ca.retention", "Piutang retensi / Retention receivables", 0, "ca", r"^Piutang retensi"),
    ("ca.other", "Piutang lain-lain / Other receivables", 0, "ca", r"^Piutang lain-lain"),
    ("ca.inv", "Persediaan / Inventories", 0, "ca", r"^Persediaan"),
    ("ca.adv", "Uang muka / Advances", 0, "ca", r"^Uang muka Advances"),
    ("ca.ptax", "Pajak dibayar di muka / Prepaid taxes", 0, "ca", r"^Pajak dibayar di muka"),
    ("ca.prep", "Biaya dibayar di muka / Prepaid expenses", 0, "ca", r"^Biaya dibayar di muka"),
    ("ca.total", "Jumlah aset lancar / Total current assets", 1, "ca", r"^Jumlah Aset Lancar"),
    ("nca.taxclaim", "Taksiran tagihan pajak penghasilan / Estimated claim for tax refund", 0, "nca", r"^Taksiran tagihan pajak"),
    ("nca.adv_inv", "Uang muka penyertaan saham / Advance for investment in shares", 0, "nca", r"^Uang muka penyertaan"),
    ("nca.shares", "Investasi saham / Investment in shares", 0, "nca", r"^(Penyertaan|Investasi) saham"),
    ("nca.adv_buy", "Uang muka pembelian aset / Advance for purchase of assets", 0, "nca", r"^Uang muka pembelian"),
    ("nca.fixed", "Aset tetap - neto / Fixed assets - net", 0, "nca", r"^Aset tetap"),
    ("nca.prop", "Properti investasi - neto / Investment properties - net", 0, "nca", r"^Properti investasi"),
    ("nca.rou", "Aset hak-guna - neto / Right-of-use assets - net", 0, "nca", r"^Aset hak-guna"),
    ("nca.intang", "Aset tak berwujud - neto / Intangible assets - net", 0, "nca", r"^Aset tak berwujud"),
    ("nca.dta", "Aset pajak tangguhan / Deferred tax assets", 0, "nca", r"^Aset pajak tangguhan"),
    ("nca.other", "Aset tidak lancar lainnya / Other non-current assets", 0, "nca", r"^Aset (lain-lain|tidak lancar lainnya)"),
    ("nca.total", "Jumlah aset tidak lancar / Total non-current assets", 1, "nca", r"^Jumlah Aset Tidak Lancar"),
    ("assets.total", "JUMLAH ASET / TOTAL ASSETS", 1, "nca", r"^JUMLAH ASET TOTAL ASSETS$"),
    ("cl.bank", "Utang bank / Bank loan", 0, "cl", r"Utang bank Bank loan"),
    ("cl.ap", "Utang usaha / Trade payables", 0, "cl", r"Utang usaha Trade payables"),
    ("cl.other", "Utang lain-lain / Other payables", 0, "cl", r"^Utang lain-lain"),
    ("cl.retention", "Utang retensi / Retention payables", 0, "cl", r"^Utang retensi"),
    ("cl.tax", "Utang pajak / Taxes payable", 0, "cl", r"^Utang pajak"),
    ("cl.accrued", "Beban akrual / Accrued expenses", 0, "cl", r"^Beban akrual"),
    ("cl.contract", "Liabilitas kontrak (2019: uang muka pelanggan) / Contract liabilities", 0, "cl", r"^(Liabilitas kontrak|Uang muka pelanggan)"),
    ("cl.unearned", "Pendapatan diterima di muka / Unearned revenue", 0, "cl", r"^Pendapatan diterima di muka"),
    ("cl.deposit", "Jaminan / Deposit", 0, "cl", r"^Jaminan"),
    ("cl.ltd", "Liabilitas jangka panjang jatuh tempo dalam satu tahun / Current maturities of long-term liabilities", 0, "cl", r"^Liabilitas jangka panjang (bagian )?yang jatuh tempo"),
    ("cl.lease", "Liabilitas sewa jatuh tempo dalam satu tahun / Current lease liabilities", 0, "cl", r"^Liabilitas sewa"),
    ("cl.total", "Jumlah liabilitas jangka pendek / Total current liabilities", 1, "cl", r"Jumlah Liabilitas Jangka Pendek"),
    ("ncl.ltd", "Liabilitas jangka panjang - setelah dikurangi bagian lancar / Long-term liabilities - net of current maturities", 0, "ncl", r"Liabilitas jangka panjang –? ?setelah"),
    ("ncl.lease", "Liabilitas sewa / Lease liabilities", 0, "ncl", r"Liabilitas sewa"),
    ("ncl.unearned", "Pendapatan diterima di muka / Unearned revenue", 0, "ncl", r"Pendapatan diterima di muka"),
    ("ncl.deposit", "Jaminan / Deposit", 0, "ncl", r"^Jaminan"),
    ("ncl.emp", "Liabilitas imbalan kerja karyawan / Employee benefits liabilities", 0, "ncl", r"^Liabilitas imbalan"),
    ("ncl.total", "Jumlah liabilitas jangka panjang / Total non-current liabilities", 1, "ncl", r"^Jumlah Liabilitas Jangka Panjang"),
    ("liab.total", "JUMLAH LIABILITAS / TOTAL LIABILITIES", 1, "eq", r"^JUMLAH LIABILITAS TOTAL LIABILITIES$"),
    ("eq.capital", "Modal saham / Share capital", 0, "eq", r"Modal saham|^Modal dasar"),
    ("eq.apic", "Tambahan modal disetor / Additional paid-in capital", 0, "eq", r"^Tambahan modal disetor"),
    ("eq.fx", "Selisih kurs penjabaran laporan keuangan / Exchange difference on translation", 0, "eq", r"^(Cadangan )?selisih kurs"),
    ("eq.re_app", "Saldo laba - telah ditentukan penggunaannya / Retained earnings - appropriated", 0, "eq", r"Telah ditentukan"),
    ("eq.re_unapp", "Saldo laba - belum ditentukan penggunaannya / Retained earnings - unappropriated", 0, "eq", r"^Belum ditentukan"),
    ("eq.parent", "Ekuitas pemilik entitas induk / Equity attributable to owners", 1, "eq", r"^Sub-jumlah"),
    ("eq.nci", "Kepentingan non-pengendali / Non-controlling interest", 0, "eq", r"^Kepentingan non"),
    ("eq.total", "JUMLAH EKUITAS / TOTAL EQUITY", 1, "eq", r"^JUMLAH EKUITAS"),
    ("le.total", "JUMLAH LIABILITAS DAN EKUITAS / TOTAL LIABILITIES AND EQUITY", 1, "eq", r"^JUMLAH LIABILITAS TOTAL LIABILITIES DAN EKUITAS"),
]
BS_NEXT = {"ca.total": "nca", "assets.total": "cl", "cl.total": "ncl", "ncl.total": "eq"}

IS = [
    ("rev", "Pendapatan / Revenues", 0, "pl", r"^PENDAPATAN( USAHA)? REVENUES"),
    ("cogs", "Beban pokok pendapatan / Cost of revenues", 0, "pl", r"^BEBAN POKOK PENDAPATAN"),
    ("gross", "LABA BRUTO / GROSS PROFIT", 1, "pl", r"^LABA BRUTO"),
    ("ga", "Beban umum dan administrasi / General and administrative expenses", 0, "pl", r"^Beban umum dan General and administrative administrasi"),
    ("_op", "Laba usaha / Operating income", 1, "pl", r"^LABA USAHA"),
    ("fv", "Laba (rugi) perubahan nilai wajar investasi / Fair value gain (loss) on investments", 0, "pl", r"atas perubahan|penyesuaian nilai"),
    ("sale", "Laba (rugi) penjualan investasi / Gain (loss) on sale of investments", 0, "pl", r"penjualan investasi|Laba penjualan|Rugi atas investasi"),
    ("rent", "Penghasilan sewa / Rent income", 0, "pl", r"^Penghasilan sewa"),
    ("finc", "Penghasilan keuangan (bunga) / Finance (interest) income", 0, "pl", r"^Penghasilan (keuangan|bunga)"),
    ("div", "Penghasilan dividen / Dividend income", 0, "pl", r"^Penghasilan dividen"),
    ("fx", "Laba (rugi) selisih kurs - neto / Foreign exchange gain (loss) - net", 0, "pl", r"^Laba( \(rugi\))? selisih kurs"),
    ("disposal", "Laba (rugi) pelepasan aset tetap / Gain (loss) on disposal of fixed assets", 0, "pl", r"pelepasan aset|penjualan aset tetap"),
    ("fincost", "Beban keuangan / Finance costs", 0, "pl", r"^Beban keuangan"),
    ("others", "Lain-lain - neto / Others - net", 0, "pl", r"^Lain-lain"),
    ("pretax_final", "LABA SEBELUM PAJAK FINAL DAN PAJAK PENGHASILAN / PROFIT BEFORE FINAL TAX AND INCOME TAX", 1, "pl", r"PAJAK FINAL DAN"),
    ("final_tax", "Beban pajak final / Final tax expense", 0, "pl", r"^Beban pajak final"),
    ("pretax", "LABA SEBELUM PAJAK PENGHASILAN / PROFIT BEFORE INCOME TAX", 1, "pl", r"^LABA SEBELUM BEBAN PROFIT BEFORE PAJAK PENGHASILAN INCOME TAX EXPENSE$"),
    ("tax.cur", "Pajak kini / Current tax", 0, "pl", r"Pajak kini"),
    ("tax.def", "Pajak tangguhan / Deferred tax", 0, "pl", r"Pajak tangguhan"),
    ("tax", "Beban pajak penghasilan - neto / Income tax expense - net", 1, "pl", r"Beban pajak penghasilan"),
    ("net", "LABA TAHUN BERJALAN / PROFIT FOR THE YEAR", 1, "pl", r"^LABA TAHUN BERJALAN"),
    ("oci.recl", "Pos yang akan direklasifikasi: selisih kurs / Items to be reclassified: exchange difference", 0, "pl", r"Pos yang akan"),
    ("oci.norecl", "Pos yang tidak akan direklasifikasi: pengukuran kembali imbalan kerja / Items not reclassified: remeasurement", 0, "pl", r"Pos yang tidak akan"),
    ("oci", "Jumlah penghasilan komprehensif lain / Total other comprehensive income", 1, "pl", r"^Jumlah penghasilan \(kerugian\) komprehensif"),
    ("ci", "JUMLAH PENGHASILAN KOMPREHENSIF / TOTAL COMPREHENSIVE INCOME", 1, "pl", r"^JUMLAH PENGHASILAN TOTAL COMPREHENSIVE"),
    ("np.parent", "Laba diatribusikan ke pemilik entitas induk / Profit attributable to owners", 0, "np", r"^Laba tahun berjalan yang dapat diatribusikan"),
    ("np.nci", "Laba diatribusikan ke kepentingan non-pengendali / to non-controlling interests", 0, "np", r"^Kepentingan non"),
    ("np.total", "Jumlah laba diatribusikan / Total", 1, "np", r"^JUMLAH TOTAL"),
    ("ci.parent", "Laba komprehensif ke pemilik entitas induk / Comprehensive income attributable to owners", 0, "ci", r"^Jumlah penghasilan komprehensif tahun"),
    ("ci.nci", "Laba komprehensif ke kepentingan non-pengendali / to non-controlling interests", 0, "ci", r"^Kepentingan non"),
    ("ci.total", "Jumlah laba komprehensif diatribusikan / Total", 1, "ci", r"^JUMLAH TOTAL"),
    ("eps", "Laba per saham dasar (Rupiah penuh) / Basic earnings per share (full Rupiah)", 0, "eps", r"per saham|PER SAHAM"),
]
IS_NEXT = {"ci": "np", "np.total": "ci", "ci.total": "eps"}

CF = [
    ("op.cust", "Penerimaan kas dari pelanggan / Cash receipts from customers", 0, "op", r"Penerimaan kas dari"),
    ("op.supp", "Pembayaran kepada pemasok (s.d. 2022 termasuk direksi dan karyawan) / Payments to suppliers (to 2022 incl. employees)", 0, "op", r"^Pembayaran kepada (pemasok|Cash payments)"),
    ("op.emp", "Pembayaran kepada karyawan / Payments to employees", 0, "op", r"^Pembayaran kepada karyawan"),
    ("op.gen", "Kas yang dihasilkan dari operasi / Cash generated from operations", 1, "op", r"^Kas yang (diperoleh|dihasilkan)"),
    ("op.int", "Penerimaan bunga / Interest received", 0, "op", r"^(Penghasilan keuangan|Penerimaan bunga)"),
    ("op.tax", "Pembayaran pajak / Payment of taxes", 0, "op", r"^Pembayaran pajak"),
    ("op.fin", "Pembayaran beban keuangan / Finance costs paid", 0, "op", r"^(Pembayaran )?beban keuangan"),
    ("op.other", "Lain-lain - neto / Others - net", 0, "op", r"^Lain-lain"),
    ("op.total", "Kas neto dari aktivitas operasi / Net cash from operating activities", 1, "op", r"^(Kas|Arus Kas) (Bersih|Neto)"),
    ("inv.sti_sale", "Hasil penjualan investasi jangka pendek / Proceeds on sale of short-term investments", 0, "inv", r"Hasil penjualan investasi Proceeds on sale of"),
    ("inv.sti_place", "Penempatan investasi jangka pendek / Placement of short-term investments", 0, "inv", r"^Penempatan investasi"),
    ("inv.sti_net", "Penjualan (penempatan) investasi jangka pendek - neto / Short-term investments - net", 0, "inv", r"Penjualan \(penempatan"),
    ("inv.share_sale", "Hasil penjualan investasi saham / Proceeds on sale of investment in shares", 0, "inv", r"investasi saham"),
    ("inv.share_place", "Penempatan penyertaan saham dan uang muka / Placement of investment in shares and advances", 0, "inv", r"^Penempatan penyertaan saham"),
    ("inv.div", "Penerimaan dividen tunai / Receipt of cash dividend", 0, "inv", r"dividen tunai"),
    ("inv.tax_sale", "Pembayaran pajak atas penjualan investasi / Payment of tax on sale of investment", 0, "inv", r"^Pembayaran pajak atas"),
    ("inv.fixed_sale", "Hasil penjualan aset tetap / Proceeds from sale of fixed assets", 0, "inv", r"Hasil penjualan.*aset tetap"),
    ("inv.capex", "Perolehan aset tetap / Acquisition of fixed assets", 0, "inv", r"^Perolehan aset tetap"),
    ("inv.rou", "Perolehan aset hak-guna / Acquisition of right-of-use assets", 0, "inv", r"^Perolehan aset hak-guna"),
    ("inv.other_nca", "Perolehan aset tidak lancar lainnya / Acquisition of other non-current assets", 0, "inv", r"^Perolehan aset tidak lancar"),
    ("inv.prop", "Perolehan properti investasi / Acquisition of investment properties", 0, "inv", r"^Perolehan properti"),
    ("inv.total", "Kas neto dari aktivitas investasi / Net cash from investing activities", 1, "inv", r"^(Kas|Arus Kas) (Bersih|Neto)"),
    ("fin.bank_in", "Penerimaan pinjaman bank / Proceeds from bank loans", 0, "fin", r"Penambahan utang bank|Penerimaan dari pinjaman bank"),
    ("fin.bank_out", "Pembayaran pinjaman bank / Repayments of bank loans", 0, "fin", r"^(Pembayaran utang bank|Pelunasan pinjaman bank)"),
    ("fin.div", "Pembayaran dividen tunai / Payments of cash dividends", 0, "fin", r"Pembayaran dividen"),
    ("fin.lease", "Pembayaran liabilitas sewa / Payments of lease liabilities", 0, "fin", r"liabilitas sewa"),
    ("fin.consumer", "Pembayaran utang pembiayaan konsumen / Payments of consumer financing debt", 0, "fin", r"pembiayaan konsumen"),
    ("fin.nci_in", "Setoran modal kepentingan non-pengendali / Capital from non-controlling interest", 0, "fin", r"^Setoran modal"),
    ("fin.nci_buy", "Akuisisi kepentingan non-pengendali / Acquisition of non-controlling interest", 0, "fin", r"^Akuisisi kepentingan"),
    ("fin.total", "Kas neto dari aktivitas pendanaan / Net cash from financing activities", 1, "fin", r"^(Kas|Arus Kas) (Bersih|Neto)"),
    # Up to LK 2024 the increase is printed before the exchange effect and
    # excludes it; LK 2025 prints the effect first and an increase that
    # includes it. Which comes first decides which line it is.
    ("chg", "Kenaikan (penurunan) kas / Net increase (decrease) in cash", 1, "end", r"^(KENAIKAN|PENURUNAN)"),
    ("fxe", "Dampak perubahan kurs / Effect of exchange rate changes", 0, "end", r"^DAMPAK"),
    ("chg_fx", "Kenaikan (penurunan) kas setelah dampak kurs / Net increase (decrease) in cash after exchange effect", 1, "after_fx", r"^(KENAIKAN|PENURUNAN)"),
    ("beg", "Kas, setara kas dan cerukan awal tahun / Cash, cash equivalents and overdraft at beginning of year", 0, "after_fx", r"AWAL TAHUN"),
    ("end", "Kas, setara kas dan cerukan akhir tahun / Cash, cash equivalents and overdraft at end of year", 1, "after_fx", r"AKHIR TAHUN"),
    ("rec.onhand", "Kas / Cash on hand", 0, "rec", r"terdiri dari.*Cash on hand"),
    ("rec.cce", "Kas dan setara kas / Cash and cash equivalents", 0, "rec", r"terdiri dari.*Kas dan setara kas"),
    ("rec.bank", "Bank / Cash in banks", 0, "rec", r"^Bank Cash in banks"),
    ("rec.td", "Deposito berjangka / Time deposits", 0, "rec", r"^Deposito berjangka Time"),
    ("rec.restricted", "Deposito berjangka yang dibatasi penggunaannya / Restricted time deposits", 0, "rec", r"^Deposito berjangka yang dibatasi"),
    ("rec.od", "Cerukan / Overdraft", 0, "rec", r"^Cerukan"),
    ("rec.total", "Jumlah / Total", 1, "rec", r"^Jumlah Total"),
]
CF_NEXT = {"op.total": "inv", "inv.total": "fin", "fin.total": "end", "fxe": "after_fx", "end": "rec"}

CHECKS = [
    ("bs", "ca.total", ["ca.cash", "ca.restricted", "ca.sti", "ca.ar", "ca.gross", "ca.retention", "ca.other", "ca.inv", "ca.adv", "ca.ptax", "ca.prep"]),
    ("bs", "nca.total", ["nca.taxclaim", "nca.adv_inv", "nca.shares", "nca.adv_buy", "nca.fixed", "nca.prop", "nca.rou", "nca.intang", "nca.dta", "nca.other"]),
    ("bs", "assets.total", ["ca.total", "nca.total"]),
    ("bs", "cl.total", ["cl.bank", "cl.ap", "cl.other", "cl.retention", "cl.tax", "cl.accrued", "cl.contract", "cl.unearned", "cl.deposit", "cl.ltd", "cl.lease"]),
    ("bs", "ncl.total", ["ncl.ltd", "ncl.lease", "ncl.unearned", "ncl.deposit", "ncl.emp"]),
    ("bs", "liab.total", ["cl.total", "ncl.total"]),
    ("bs", "eq.parent", ["eq.capital", "eq.apic", "eq.fx", "eq.re_app", "eq.re_unapp"]),
    ("bs", "eq.total", ["eq.parent", "eq.nci"]),
    ("bs", "le.total", ["liab.total", "eq.total"]),
    ("bs", "le.total", ["assets.total"]),
    ("is", "gross", ["rev", "cogs"]),
    ("is", "_op", ["gross", "ga"]),
    ("is", "pretax_final", ["gross", "ga", "fv", "sale", "rent", "finc", "div", "fx", "disposal", "fincost", "others"]),
    ("is", "pretax", ["pretax_final", "final_tax"]),
    ("is", "tax", ["tax.cur", "tax.def"], "tax.cur"),
    ("is", "net", ["pretax", "tax"]),
    ("is", "oci", ["oci.recl", "oci.norecl"]),
    ("is", "ci", ["net", "oci.recl", "oci.norecl"]),
    ("is", "np.total", ["np.parent", "np.nci"]),
    ("is", "np.total", ["net"]),
    ("is", "ci.total", ["ci.parent", "ci.nci"]),
    ("is", "ci.total", ["ci"]),
    ("cf", "op.gen", ["op.cust", "op.supp", "op.emp"]),
    ("cf", "op.total", ["op.gen", "op.int", "op.tax", "op.fin", "op.other"]),
    ("cf", "inv.total", ["inv.sti_sale", "inv.sti_place", "inv.sti_net", "inv.share_sale", "inv.share_place", "inv.div",
                         "inv.tax_sale", "inv.fixed_sale", "inv.capex", "inv.rou", "inv.other_nca", "inv.prop"]),
    ("cf", "fin.total", ["fin.bank_in", "fin.bank_out", "fin.div", "fin.lease", "fin.consumer", "fin.nci_in", "fin.nci_buy"]),
    ("cf", "chg", ["op.total", "inv.total", "fin.total"]),
    ("cf", "chg_fx", ["op.total", "inv.total", "fin.total", "fxe"]),
    ("cf", "end", ["beg", "chg", "fxe"], "chg"),
    ("cf", "end", ["beg", "chg_fx"], "chg_fx"),
    ("cf", "rec.total", ["rec.onhand", "rec.cce", "rec.bank", "rec.td", "rec.restricted", "rec.od"]),
    ("cf", "rec.total", ["end"]),
]
STATEMENTS = [
    ("bs", "balance_sheet", "Neraca", BS, BS_NEXT, "ca"),
    ("is", "income_statement", "Laba Rugi", IS, IS_NEXT, "pl"),
    ("cf", "cash_flow", "Arus Kas", CF, CF_NEXT, "op"),
]

# A header row goes above the first line of each group: (text, is_band).
SECTIONS = {
    "ca": [("ASET / ASSETS", True), ("Aset lancar / Current assets", False)],
    "nca": [("Aset tidak lancar / Non-current assets", False)],
    "cl": [("LIABILITAS DAN EKUITAS / LIABILITIES AND EQUITY", True),
           ("Liabilitas jangka pendek / Current liabilities", False)],
    "ncl": [("Liabilitas jangka panjang / Non-current liabilities", False)],
    "eq": [("Ekuitas / Equity", False)],
    "np": [("Laba diatribusikan kepada / Profit attributable to", False)],
    "ci": [("Laba komprehensif diatribusikan kepada / Comprehensive income attributable to", False)],
    "op": [("Arus kas dari aktivitas operasi / Cash flows from operating activities", True)],
    "inv": [("Arus kas dari aktivitas investasi / Cash flows from investing activities", True)],
    "fin": [("Arus kas dari aktivitas pendanaan / Cash flows from financing activities", True)],
    "rec": [("Kas, setara kas dan cerukan akhir tahun terdiri dari / Consisting of", False)],
}
NOTES = [
    "Sumber: laporan keuangan konsolidasian auditan 31 Desember, www.paramita.co.id/fin-statement.php.",
    "Tiap tahun diambil dari laporan terbaru yang memuatnya, jadi angka yang disajikan kembali menggantikan angka aslinya:",
    "  2024 dan 2025 dari LK 2025; 2023 dari LK 2024; 2022 dari LK 2023; 2021 dari LK 2022; 2020 dari LK 2021; 2019 dari LK 2020.",
    "Semua angka dalam Rupiah penuh, seperti tercetak di laporan.",
    "Kas di arus kas termasuk cerukan (dan deposito yang dibatasi pada 2024), jadi bisa berbeda dari kas di neraca;",
    "  rinciannya ada di bagian bawah sheet Arus Kas.",
    "Laba per saham 2019 dan 2020 memakai nilai nominal Rp 100 (1,5 miliar saham). Sejak 2021 laporan memakai",
    "  Rp 50 (3 miliar saham, pemecahan saham 2022), jadi laba per saham 2019-2020 tidak sebanding dengan tahun sesudahnya.",
    "Laporan 2019-2022 mencetak satu baris pembayaran kepada pemasok, direksi dan karyawan; sejak 2023 dipisah.",
    "Laporan entitas induk saja (di belakang laporan 2021-2024) tidak dipakai.",
]

build(
    company="PT Paramita Bangun Sarana Tbk dan Entitas Anak", ticker="PBSA.IJ", pdf=PDF, reports=REPORTS,
    years=YEARS, statements=STATEMENTS, checks=CHECKS, sections=SECTIONS, notes=NOTES, out=OUT,
    unit="Rupiah", unit_label="Rupiah", min_figure=1000, width=19,
)
