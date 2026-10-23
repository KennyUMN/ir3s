"""DEWA 2022-2025 on one set of line items, newest report per year.

The 2025 report changed its layout and wording, so a printed line is matched
to a standard line by rule, within the part of the statement it sits in.
Every printed figure must match a rule, and every subtotal must equal the
sum of its lines, or the script stops.
"""
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from statements_xlsx import build  # noqa: E402

# The December reports from www.ptdh.co.id/investor/financial-statement,
# saved as dewa_fs_<year>.pdf.
PDF_DIR = os.environ.get("DEWA_PDF_DIR", os.path.expanduser("~/.hermes/cache/scratch/audit/dewa"))
PDF = os.path.join(PDF_DIR, "dewa_fs_{}.pdf")
OUT = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "DEWA_2022_2025.xlsx")
YEARS = [2022, 2023, 2024, 2025]
REPORTS = [2025, 2024, 2023]  # newest first: a restated figure wins
# Page footers and note references that land in a figure column.
JUNK = re.compile(r"tidak terpisahkan|Lihat Catatan|\(Pindahan\)|secara financial statements", re.I)

# (key, display label, is_total, part, pattern). The part is where in the
# statement the line sits; a part ends at the total that closes it.
BS = [
    ("ca.cash", "Kas dan setara kas / Cash and cash equivalents", 0, "ca", r"^Kas dan setara kas"),
    ("ca.ar_rel", "Piutang usaha - pihak berelasi / Trade receivables - related parties", 0, "ca", r"^Piutang usaha.*Pihak berelasi"),
    ("ca.ar_3rd", "Piutang usaha - pihak ketiga / Trade receivables - third parties", 0, "ca", r"^Piutang usaha.*Pihak ketiga"),
    ("ca.due_rel", "Piutang pihak berelasi / Due from related parties", 0, "ca", r"^Piutang pihak berelasi"),
    ("ca.inv", "Persediaan / Inventories", 0, "ca", r"^Persediaan"),
    ("ca.ptax", "Pajak dibayar di muka / Prepaid taxes", 0, "ca", r"^Pajak dibayar di muka"),
    ("ca.prep", "Beban dibayar di muka / Prepayments", 0, "ca", r"^(Biaya|Beban) dibayar di muka"),
    ("ca.other", "Aset lancar lainnya / Other current assets", 0, "ca", r"^Aset lancar lainnya"),
    ("ca.total", "Jumlah aset lancar / Total current assets", 1, "ca", r"^Jumlah aset lancar"),
    ("nca.taxclaim", "Taksiran tagihan pajak / Estimated claims for tax refund", 0, "nca", r"Taksiran tagihan pajak"),
    ("nca.dta", "Aset pajak tangguhan / Deferred tax assets", 0, "nca", r"^Aset pajak tangguhan"),
    ("nca.assoc", "Investasi pada entitas asosiasi / Investment in associates", 0, "nca", r"^Investasi pada entitas asosiasi"),
    ("nca.fin", "Aset keuangan tidak lancar / Non-current financial assets", 0, "nca", r"^Aset keuangan tidak lancar"),
    ("nca.shares", "Investasi pada saham / Investment in shares", 0, "nca", r"^Investasi pada saham"),
    ("nca.fixed", "Aset tetap / Fixed assets", 0, "nca", r"^Aset tetap"),
    ("nca.expl", "Aset eksplorasi dan evaluasi / Exploration and evaluation assets", 0, "nca", r"^Aset eksplorasi"),
    ("nca.rou", "Aset hak-guna / Right-of-use assets", 0, "nca", r"^Aset hak-guna"),
    ("nca.other", "Aset tidak lancar lainnya / Other non-current assets", 0, "nca", r"^Aset tidak lancar lainnya"),
    ("nca.total", "Jumlah aset tidak lancar / Total non-current assets", 1, "nca", r"^Jumlah aset tidak lancar"),
    ("assets.total", "JUMLAH ASET / TOTAL ASSETS", 1, "nca", r"^JUMLAH ASET\s+TOTAL ASSETS$"),
    ("cl.ap", "Utang usaha - pihak ketiga / Trade payables - third parties", 0, "cl", r"Utang usaha"),
    ("cl.unearned", "Pendapatan diterima di muka / Unearned revenue", 0, "cl", r"^Pendapatan diterima di muka"),
    ("cl.tax", "Utang pajak / Taxes payable", 0, "cl", r"^Utang pajak"),
    ("cl.accrued", "Beban akrual / Accrued expenses", 0, "cl", r"^(Beban akrual|Beban yang masih harus dibayar)"),
    ("cl.adv", "Uang muka pelanggan / Advances from customers", 0, "cl", r"^Uang muka pelanggan"),
    ("cl.bank", "Pinjaman bank jatuh tempo satu tahun / Current portion of bank loans", 0, "cl", r"(Utang bank|Pinjaman bank) Bank loans$"),
    ("cl.finlease", "Utang sewa pembiayaan / Finance lease payables", 0, "cl", r"^Utang sewa pembiayaan"),
    ("cl.lease", "Liabilitas sewa / Lease liabilities", 0, "cl", r"^Liabilitas sewa"),
    ("cl.other", "Utang lain-lain - pihak ketiga / Other payables - third parties", 0, "cl", r"^Utang lain-lain"),
    ("cl.total", "Jumlah liabilitas jangka pendek / Total current liabilities", 1, "cl", r"^Jumlah liabilitas jangka pendek"),
    ("ncl.bank", "Pinjaman bank jangka panjang / Long-term bank loans", 0, "ncl", r"(Utang bank|Pinjaman bank) Bank loans$"),
    ("ncl.finlease", "Utang sewa pembiayaan / Finance lease payables", 0, "ncl", r"^Utang sewa pembiayaan"),
    ("ncl.lease", "Liabilitas sewa / Lease liabilities", 0, "ncl", r"^Liabilitas sewa"),
    ("ncl.other", "Utang lain-lain - pihak ketiga / Other payables - third parties", 0, "ncl", r"^Utang lain-lain"),
    ("ncl.due_rel", "Utang pihak berelasi / Due to related parties", 0, "ncl", r"^Utang pihak berelasi"),
    ("ncl.dtl", "Liabilitas pajak tangguhan / Deferred tax liabilities", 0, "ncl", r"^Liabilitas pajak tangguhan"),
    ("ncl.emp", "Liabilitas imbalan pascakerja / Post-employment benefits", 0, "ncl", r"(Imbalan Pascakerja|imbalan pasca-)"),
    ("ncl.total", "Jumlah liabilitas jangka panjang / Total non-current liabilities", 1, "ncl", r"^Jumlah liabilitas jangka"),
    ("liab.total", "JUMLAH LIABILITAS / TOTAL LIABILITIES", 1, "eq", r"^JUMLAH LIABILITAS TOTAL LIABILITIES(\s*\(Dipindahkan\).*)?$"),
    ("eq.capital", "Modal saham / Share capital", 0, "eq", r"^(Ekuitas yang dapat.*Modal saham|2024 dan 2023)"),
    ("eq.treasury", "Saham treasuri / Treasury shares", 0, "eq", r"^Saham treasuri"),
    ("eq.apic", "Tambahan modal disetor / Additional paid-in capital", 0, "eq", r"^Tambahan modal disetor"),
    ("eq.fx", "Penyesuaian perubahan mata uang / Currency adjustment", 0, "eq", r"^Penyesuaian perubahan mata uang"),
    ("eq.oce", "Komponen ekuitas lainnya / Other equity components", 0, "eq", r"^Komponen ekuitas lainnya"),
    ("eq.re", "Saldo laba (defisit) / Retained earnings (deficit)", 0, "eq", r"^(Saldo laba|Defisit)"),
    ("eq.parent", "Ekuitas pemilik entitas induk / Equity attributable to owners", 1, "eq", r"^Sub[- ]jumlah"),
    ("eq.nci", "Kepentingan non-pengendali / Non-controlling interests", 0, "eq", r"^Kepentingan non-?pengendali"),
    ("eq.total", "JUMLAH EKUITAS / TOTAL EQUITY", 1, "eq", r"^JUMLAH EKUITAS"),
    ("le.total", "JUMLAH LIABILITAS DAN EKUITAS / TOTAL LIABILITIES AND EQUITY", 1, "eq", r"^JUMLAH LIABILITAS.*EKUITAS"),
]
BS_NEXT = {"ca.total": "nca", "assets.total": "cl", "cl.total": "ncl", "ncl.total": "eq"}

IS = [
    ("rev", "Pendapatan / Revenues", 0, "pl", r"^PENDAPATAN REVENUES"),
    ("cogs", "Beban pokok pendapatan / Cost of revenues", 0, "pl", r"^BEBAN POKOK"),
    ("gross", "LABA BRUTO / GROSS PROFIT", 1, "pl", r"^LABA BRUTO"),
    ("ga", "Beban umum dan administrasi / General and administrative expenses", 0, "pl", r"^Beban umum dan administrasi"),
    ("optax", "Beban pajak (selain pajak penghasilan) / Tax expense", 0, "pl", r"^Beban pajak"),
    ("finc", "Penghasilan bunga dan keuangan / Interest and finance income", 0, "pl", r"^(Penghasilan bunga|Penghasilan keuangan)"),
    ("fincost", "Beban keuangan / Finance cost", 0, "pl", r"^Beban keuangan"),
    ("fx", "Laba (rugi) selisih kurs - neto / Foreign exchange gain (loss) - net", 0, "pl", r"selisih kurs"),
    ("disposal", "Laba pelepasan aset tetap / Gain on disposal of fixed assets", 0, "pl", r"^Laba atas Pelepasan"),
    ("assoc", "Bagian laba entitas asosiasi / Share in profit of associates", 0, "pl", r"^Bagian laba"),
    ("others", "Lain-lain - neto / Others - net", 0, "pl", r"^Lain-lain"),
    # Printed only by the 2023 and 2024 reports: checked, not shown.
    ("_other_total", "", 1, "pl", r"^JUMLAH BEBAN LAIN-LAIN"),
    ("_op_profit", "", 1, "pl", r"^LABA USAHA"),
    ("pretax", "LABA (RUGI) SEBELUM PAJAK / PROFIT (LOSS) BEFORE TAX", 1, "pl", r"^LABA (\(RUGI\) )?SEBELUM"),
    ("tax.cur", "Pajak kini / Current tax", 0, "pl", r"^Kini"),
    ("tax.def", "Pajak tangguhan / Deferred tax", 0, "pl", r"^Tangguhan"),
    ("tax", "Jumlah pajak penghasilan / Total income tax", 1, "pl", r"^(Jumlah Pajak Penghasilan|MANFAAT PAJAK PENGHASILAN|PAJAK PENGHASILAN)"),
    ("net", "LABA (RUGI) TAHUN BERJALAN / PROFIT (LOSS) FOR THE YEAR", 1, "pl", r"^LABA (\(RUGI\) )?TAHUN BERJALAN (CURRENT YEAR|PROFIT FOR THE YEAR)$"),
    ("oci.remeas", "Pengukuran kembali imbalan pasti / Remeasurement of defined benefit", 0, "pl", r"^PENGHASILAN (\(BEBAN\) )?(OTHER COMPREHENSIVE|KOMPREHENSIF LAIN)"),
    ("oci.tax", "Pajak terkait / Related income tax", 0, "pl", r"^Pajak penghasilan terkait"),
    ("oci", "Penghasilan komprehensif lain / Other comprehensive income", 1, "pl", r"(^Penghasilan Komprehensif Lain Other|Tahun Berjalan setelah Pajak|^JUMLAH PENGHASILAN)"),
    ("ci", "JUMLAH LABA KOMPREHENSIF / TOTAL COMPREHENSIVE INCOME", 1, "pl", r"JUMLAH LABA (\(RUGI\) )?KOMPREHENSIF TOTAL COMPREHENSIVE INCOME TAHUN BERJALAN (\(LOSS\) )?FOR"),
    ("np.parent", "Laba diatribusikan ke pemilik entitas induk / Profit attributable to owners", 0, "pl", r"(TAHUN BERJALAN YANG|^Laba tahun berjalan yang)"),
    ("np.nci", "Laba diatribusikan ke kepentingan non-pengendali / to non-controlling interests", 0, "np", r"Kepentingan non-?pengendali"),
    ("np.total", "Jumlah laba diatribusikan / Total", 1, "np", r"^Jumlah Total"),
    ("ci.parent", "Laba komprehensif ke pemilik entitas induk / Comprehensive income to owners", 0, "pl", r"(KOMPREHENSIF TOTAL COMPREHENSIVE (INCOME )?TAHUN BERJALAN YANG|KOMPREHENSIF TAHUN BERJALAN YANG|^Jumlah laba komprehensif tahun)"),
    ("ci.nci", "Laba komprehensif ke kepentingan non-pengendali / to non-controlling interests", 0, "ci", r"Kepentingan non-?pengendali"),
    ("ci.total", "Jumlah laba komprehensif diatribusikan / Total", 1, "ci", r"^Jumlah Total"),
    ("eps", "Laba (rugi) per saham dasar, per 1.000 saham (Rupiah penuh) / Basic EPS per 1,000 shares", 0, "ci", r"PER SAHAM"),
]
IS_NEXT = {"np.parent": "np", "np.total": "pl", "ci.parent": "ci"}

CF = [
    ("op.cust", "Penerimaan dari pelanggan / Receipts from customers", 0, "op", r"Penerimaan dari pelanggan"),
    ("op.supp", "Pembayaran kepada pemasok dan subkontraktor / Payments to suppliers", 0, "op", r"Pembayaran kepada pemasok"),
    ("op.emp", "Pembayaran kepada karyawan / Payments to employees", 0, "op", r"Pembayaran kepada karyawan"),
    ("_op_sub", "", 1, "op", r"^Arus kas dari operasi"),
    ("op.taxclaim", "Penerimaan restitusi pajak / Receipts from tax refunds", 0, "op", r"(Restitusi Pajak|Penerimaan dari taksiran)"),
    ("op.int", "Penerimaan bunga dan penghasilan keuangan / Interest and finance income received", 0, "op", r"(Penerimaan Penghasilan Bunga|Penerimaan dari penghasilan keuangan)"),
    ("op.tax", "Pembayaran pajak / Taxes paid", 0, "op", r"(^Pembayaran Pajak|Pembayaran atas pajak penghasilan)"),
    ("op.fin", "Pembayaran bunga dan beban keuangan / Interest and finance cost paid", 0, "op", r"(^Pembayaran Bunga|Pembayaran atas beban keuangan)"),
    ("op.total", "Kas neto dari aktivitas operasi / Net cash from operating activities", 1, "op", r"(Net Cash Provided by Aktivitas Operasi|Net cash flows from operating)"),
    ("inv.rel", "Penerimaan (pembayaran) pihak berelasi / Related parties", 0, "inv", r"(Pihak Berelasi Related Parties|Penerimaan dari pihak berelasi)"),
    ("inv.acq", "Kas masuk dari akuisisi entitas anak / Cash from acquisition of subsidiary", 0, "inv", r"akuisisi"),
    ("inv.div", "Kas keluar dari pelepasan entitas anak / Cash out on divestment", 0, "inv", r"pelepasan Net cash outflow"),
    ("inv.sale", "Penerimaan dari penjualan aset tetap / Proceeds from sale of fixed assets", 0, "inv", r"(Pelepasan Aset Tetap|penjualan aset tetap)"),
    ("inv.capex", "Perolehan aset tetap / Acquisition of fixed assets", 0, "inv", r"(Pembelian Aset Tetap|Perolehan aset tetap)"),
    ("inv.total", "Kas neto dari aktivitas investasi / Net cash from investing activities", 1, "inv", r"(Net Cash Used in Investing|Net cash flows for investing)"),
    ("fin.bank_in", "Penerimaan pinjaman bank / Proceeds from bank loans", 0, "fin", r"(Penerimaan Utang Bank|pinjaman bank jangka panjang Proceed)"),
    ("fin.other_in", "Penerimaan utang lain-lain / Receipts of other payables", 0, "fin", r"Penerimaan (dari )?utang lain-lain"),
    ("fin.issue", "Pembayaran biaya emisi saham / Share issuance costs", 0, "fin", r"biaya emisi"),
    ("fin.finlease", "Pembayaran utang sewa pembiayaan / Repayment of finance leases", 0, "fin", r"Pembayaran utang sewa pembiayaan"),
    ("fin.lease", "Pembayaran liabilitas sewa / Repayment of lease liabilities", 0, "fin", r"Pembayaran (atas )?liabilitas sewa"),
    ("fin.treasury", "Pembelian saham treasuri / Purchase of treasury shares", 0, "fin", r"saham treasuri"),
    ("fin.other_out", "Pembayaran utang lain-lain / Repayment of other payables", 0, "fin", r"Pembayaran (atas )?utang lain-lain"),
    ("fin.bank_out", "Pembayaran pinjaman bank / Repayment of bank loans", 0, "fin", r"(Pembayaran Utang Bank|Pembayaran atas pinjaman bank)"),
    ("fin.total", "Kas neto dari aktivitas pendanaan / Net cash from financing activities", 1, "fin", r"(Aktivitas Pendanaan Financing Activities|Pe$|Net cash flows from financing)"),
    ("chg", "Kenaikan (penurunan) kas dan setara kas / Net change in cash", 1, "end", r"^KENAIKAN"),
    ("fxe", "Dampak perubahan selisih kurs / Effect of exchange rate changes", 0, "end", r"^DAMPAK"),
    ("beg", "Kas dan setara kas awal tahun / Cash at beginning of year", 0, "end", r"AWAL TAHUN"),
    ("end", "Kas dan setara kas akhir tahun / Cash at end of year", 1, "end", r"AKHIR TAHUN"),
]
CF_NEXT = {"op.total": "inv", "inv.total": "fin", "fin.total": "end"}

# Each identity: (statement, total key, component keys).
CHECKS = [
    ("bs", "ca.total", ["ca.cash", "ca.ar_rel", "ca.ar_3rd", "ca.due_rel", "ca.inv", "ca.ptax", "ca.prep", "ca.other"]),
    ("bs", "nca.total", ["nca.taxclaim", "nca.dta", "nca.assoc", "nca.fin", "nca.shares", "nca.fixed", "nca.expl", "nca.rou", "nca.other"]),
    ("bs", "assets.total", ["ca.total", "nca.total"]),
    ("bs", "cl.total", ["cl.ap", "cl.unearned", "cl.tax", "cl.accrued", "cl.adv", "cl.bank", "cl.finlease", "cl.lease", "cl.other"]),
    ("bs", "ncl.total", ["ncl.bank", "ncl.finlease", "ncl.lease", "ncl.other", "ncl.due_rel", "ncl.dtl", "ncl.emp"]),
    ("bs", "liab.total", ["cl.total", "ncl.total"]),
    ("bs", "eq.parent", ["eq.capital", "eq.treasury", "eq.apic", "eq.fx", "eq.oce", "eq.re"]),
    ("bs", "eq.total", ["eq.parent", "eq.nci"]),
    ("bs", "le.total", ["liab.total", "eq.total"]),
    ("bs", "le.total", ["assets.total"]),
    ("is", "gross", ["rev", "cogs"]),
    ("is", "_other_total", ["ga", "optax", "finc", "fx", "disposal", "others"]),
    ("is", "_op_profit", ["gross", "_other_total"]),
    ("is", "pretax", ["gross", "ga", "optax", "finc", "fincost", "fx", "disposal", "assoc", "others"]),
    ("is", "net", ["pretax", "tax"]),
    ("is", "ci", ["net", "oci"]),
    ("is", "np.total", ["np.parent", "np.nci"]),
    ("is", "np.total", ["net"]),
    ("is", "ci.total", ["ci.parent", "ci.nci"]),
    ("is", "ci.total", ["ci"]),
    ("cf", "_op_sub", ["op.cust", "op.supp", "op.emp"]),
    ("cf", "op.total", ["op.cust", "op.supp", "op.emp", "op.taxclaim", "op.int", "op.tax", "op.fin"]),
    ("cf", "inv.total", ["inv.rel", "inv.acq", "inv.div", "inv.sale", "inv.capex"]),
    ("cf", "fin.total", ["fin.bank_in", "fin.other_in", "fin.issue", "fin.finlease", "fin.lease", "fin.treasury", "fin.other_out", "fin.bank_out"]),
    ("cf", "chg", ["op.total", "inv.total", "fin.total"]),
    ("cf", "end", ["beg", "chg", "fxe"]),
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
}
NOTES = [
    "Sumber: laporan keuangan konsolidasian auditan 31 Desember, www.ptdh.co.id/investor/financial-statement.",
    "Tiap tahun diambil dari laporan terbaru yang memuatnya, jadi angka yang disajikan kembali menggantikan angka aslinya.",
    "  Neraca 2023, 2024, 2025 dan laba rugi / arus kas 2024, 2025: LK 2025 (disajikan kembali, Catatan 3).",
    "  Laba rugi / arus kas 2023: LK 2024. Semua laporan 2022: LK 2023 (disajikan dalam Rupiah).",
    "Sebelum 2023 DEWA melapor dalam Dolar AS; 2019-2021 tidak dimasukkan.",
    "Laporan 2023 dan 2024 mencetak subtotal 'Laba usaha' dan 'Jumlah beban lain-lain'; laporan 2025 tidak, jadi",
    "  keduanya tidak ditampilkan. Laba sebelum pajak = laba bruto + semua pos di bawahnya, di setiap tahun.",
    "Laporan 2025 mencetak subtotal 'Arus kas dari operasi - bersih' yang tidak ada di laporan lama; tidak ditampilkan.",
]

build(
    company="PT Darma Henwa Tbk dan Entitas Anak", ticker="DEWA.IJ", pdf=PDF, reports=REPORTS,
    years=YEARS, statements=STATEMENTS, checks=CHECKS, sections=SECTIONS, notes=NOTES, out=OUT,
    unit="thousands", unit_label="Ribu IDR", min_figure=50, junk=JUNK, cash_tie=("ca.cash", "end"),
)
