# main.py
import os,sys
import json
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont
import platform

import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.utils import ImageReader
import barcode
from barcode.writer import ImageWriter
from barcode import get_barcode_class
import win32api, pywintypes
from datetime import datetime, timedelta
import textwrap
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle


if getattr(sys, "frozen", False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(__file__)

DATABASE = os.path.join(base_path, "billing_system.db")
WHATSAPP_SERVER_URL = "http://localhost:3000/send-message"

# Change these to your designated printer names (as recognized by your OS)
BILL_PRINTER = "IHR810"
BARCODE_PRINTER = "TSC TE244"

def set_scaling(root, factor=1.5):
    try:
        root.tk.call('tk', 'scaling', factor)
    except Exception:
        pass

def start_node_server():
    """Launch the Node.js server as a background process."""
    try:
        subprocess.Popen(["node", os.path.join(base_path, "server.js")], cwd=base_path)
        print("Started Node.js WhatsApp server.")
    except Exception as e:
        print("Error starting Node.js server:", e)

def initialize_db():
    """Initialize the SQLite database and add new columns if needed."""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    # Create bills table with boolean flags
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            bill_number TEXT,
            total_amount REAL,
            details TEXT,
            cart_data TEXT,
            pdf_path TEXT,
            bill_date TEXT,
            completed INTEGER DEFAULT 0,
            delivered_date TEXT,
            is_cash INTEGER DEFAULT 0,
            is_gpay INTEGER DEFAULT 0,
            is_indusind_bank INTEGER DEFAULT 0,
            FOREIGN KEY (customer_id) REFERENCES customerentry(id)
        )
    """)
    # Ensure legacy schemas get new columns
    for col, col_def in [("is_cash","INTEGER DEFAULT 0"),("is_gpay","INTEGER DEFAULT 0"),("is_indusind_bank","INTEGER DEFAULT 0"),("delivered_date","TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE bills ADD COLUMN {col} {col_def}")
        except sqlite3.OperationalError:
            pass
    try:
        cursor.execute("ALTER TABLE itemlist ADD COLUMN price REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # also for servicelist if you wish
    try:
        cursor.execute("ALTER TABLE servicelist ADD COLUMN price REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

_conn = sqlite3.connect(DATABASE)
_cur = _conn.cursor()
for col in ("is_cash","is_gpay","is_indusind_bank"):
    try:
        _cur.execute(f"ALTER TABLE bills ADD COLUMN {col} INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
_conn.commit()
_conn.close()

def generate_barcode(
    data,
    filename_prefix,
    display_text=None,
    dpi=203,
    target_mm_width=40,
    add_text_above=False
):
    import os, textwrap
    from datetime import datetime, timedelta
    from PIL import Image, ImageDraw, ImageFont
    import qrcode

    base_path = os.path.dirname(__file__)
    font_black = os.path.join(base_path, "arial_black.ttf")
    font_bold  = os.path.join(base_path, "arial_bold.ttf")

    def mm_to_px(mm):
        return int(dpi * mm / 25.4)

    # ─── 1. Generate QR Code ───
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=1,
    )
    qr.add_data(str(data))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("L")

    # ✅ Skip layout for bill QR (no text, no resize)
    if display_text is None:
        qr_img.save(f"{filename_prefix}.png", dpi=(dpi, dpi))
        return f"{filename_prefix}.png"

    # ─── 2. Layout Sizing ───
    full_qr_px = mm_to_px(target_mm_width)
    qr_visual_px = int(full_qr_px * 0.6)  # keep square ratio
    qr_img = qr_img.resize((qr_visual_px, qr_visual_px), Image.NEAREST)

    # ─── 3. Fonts ───
    header_font = ImageFont.truetype(font_black, mm_to_px(4))
    footer_font = ImageFont.truetype(font_black, mm_to_px(4))
    date_font   = ImageFont.truetype(font_black, mm_to_px(4))
    draw_dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # ─── 4. Header ───
    header_text = "Laundry Billing and Barcode Tagging System"
    header_w, header_h = draw_dummy.textbbox((0, 0), header_text, font=header_font)[2:]

    # ─── 5. Footer Text (with wrapping) ───
    footer_lines = []
    bill_no_text = f"Bill No: {data.split('_')[0]}" if "_" in data else f"Bill No: {data}"

    if display_text:
        parts = [p.strip() for p in display_text.split("|")]
        while len(parts) < 3:
            parts.append("")

        max_line_width = full_qr_px
        max_lines_per_part = 2

        for i, part in enumerate(parts[:3]):
            if not part:
                continue

            if i == 1:  # item name only
                item_name = part
                item_name_lower = item_name.lower()

                label = ""
                if "light" in item_name_lower:
                    label = "(lgt)"
                elif "medium" in item_name_lower or "med" in item_name_lower:
                    label = "(med)"
                elif "heavy" in item_name_lower:
                    label = "(hvy)"

                bbox = draw_dummy.textbbox((0, 0), item_name, font=footer_font)
                avg_char_w = (bbox[2] - bbox[0]) / max(len(item_name), 1)
                max_chars = max(5, int(full_qr_px / avg_char_w))

                wrapped = textwrap.wrap(item_name, width=max_chars)
                wrapped = wrapped[:2]  # limit item to 2 lines

                if label:
                    wrapped.append(label)  # label on 3rd line

                footer_lines.extend(wrapped)
            else:
                bbox = draw_dummy.textbbox((0, 0), part, font=footer_font)
                avg_char_w = (bbox[2] - bbox[0]) / max(len(part), 1)
                max_chars = max(5, int(full_qr_px / avg_char_w))

                wrapped = textwrap.wrap(part, width=max_chars)
                footer_lines.extend(wrapped[:max_lines_per_part])

    footer_lines.append(bill_no_text)
    footer_heights = [footer_font.getbbox(line)[3] for line in footer_lines]
    footer_h = sum(footer_heights) + 5 * (len(footer_lines) - 1)

    # ─── 6. Date ───
    today = datetime.now()
    start = today.strftime('%d/%m/%Y')
    end   = (today + timedelta(days=4)).strftime('%d/%m/%Y')
    date_gap = 4
    date_line_height = date_font.getbbox("Ag")[3]
    bottom_padding = 10  # ← extra bottom space under date
    date_h = date_line_height * 2 + date_gap + bottom_padding

    # ─── 7. Canvas ───
    margin_lr = 8
    margin_tb = mm_to_px(2.5)
    spacing_header_barcode = 10
    spacing_barcode_footer = 5
    spacing_footer_date = 5

    total_h = (
        margin_tb + header_h + spacing_header_barcode +
        qr_visual_px + spacing_barcode_footer +
        footer_h + spacing_footer_date + date_h + margin_tb
    )

    canvas = Image.new("L", (full_qr_px + 2 * margin_lr, total_h), "white")
    draw = ImageDraw.Draw(canvas)

    # ─── 8. Draw Everything ───
    y = margin_tb
    draw.text(((canvas.width - header_w) // 2, y), header_text, font=header_font, fill="black")
    y += header_h + spacing_header_barcode

    canvas.paste(qr_img, ((canvas.width - qr_visual_px) // 2, y))
    y += qr_visual_px + spacing_barcode_footer

    for idx, line in enumerate(footer_lines):
        draw.text((margin_lr + 2, y), line, font=footer_font, fill="black")
        y += footer_heights[idx] + 5

    # Dates with bottom padding
    draw.text((margin_lr + 2, y), start, font=date_font, fill="black")
    y += date_line_height + date_gap
    draw.text((margin_lr + 2, y), end, font=date_font, fill="black")
    y += date_line_height + bottom_padding  # bottom padding

    # ─── 9. Save ───
    out_path = f"{filename_prefix}.png"
    bw_canvas = canvas.point(lambda x: 0 if x < 160 else 255, "1")
    bw_canvas.save(out_path, dpi=(dpi, dpi))

    return out_path


from PIL import Image, ImageEnhance
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
import os
from datetime import datetime, timedelta

def generate_bill_pdf(
    customer_name,
    customer_phone,
    details,
    total_amount,
    bill_number,
    cart_items,
    discount_amount=0,
    advance_amount=0,
    payment_mode="",
    delivery_date=None,
):
    if delivery_date is None:
        delivery_date = (datetime.now() + timedelta(days=3)).strftime("%d/%m/%Y")

    # 1) Styles (now using Times-Bold for maximum contrast)
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Times-Bold",    # ↑ changed from Times-Roman
        fontSize=8,
        leading=8,
        textColor=colors.black,   # ensure pure black
    )
    bold = ParagraphStyle(
        "Bold",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=8,
        leading=8,
        textColor=colors.black,
    )
    font_black = os.path.join(base_path, "arial_black.ttf")
    total = ParagraphStyle(
        "Bold",
        parent=styles["Normal"],
        fontName="Times-Bold",
        fontSize=10,
        leading=10,
        textColor=colors.black,
    )

    # 2) Build table data
    data = [[Paragraph("Item", bold),
             Paragraph("Service", bold),
             Paragraph("Qty", bold),
             Paragraph("Price", bold),
             Paragraph("Sub Total", bold)]]

    grouped = {}
    for prod, srv, price, qty, _, _ in cart_items:
        key = (prod, srv)
        grouped.setdefault(key, {"qty": 0, "price": price})
        grouped[key]["qty"] += qty

    for (name, service), info in grouped.items():
        sub = info["qty"] * info["price"]
        data.append([
            Paragraph(name, body),
            Paragraph(service, body),
            Paragraph(str(info["qty"]), body),
            Paragraph(f"Rs {info['price']:.2f}", body),
            Paragraph(f"Rs {sub:.2f}", body),
        ])
    net = total_amount - discount_amount - advance_amount
    total_units = sum(units for _, _, _, _, units, _ in cart_items)
    data.append([
        Paragraph("", body),  # Item
        Paragraph("", body),  # Service
        Paragraph(f"Total: Rs {net:.2f}", total),  # Merged Cell
        "",  # placeholder for colspan
        ""   # placeholder for colspan
    ])

    # 3) Table layout
    page_w = 78 * mm
    margin = 2 * mm  # reduced margin
    usable_w = page_w - 2 * margin

    col_w = [
        usable_w * 0.32,  # Item
        usable_w * 0.2,   # Service
        usable_w * 0.12,  # Qty
        usable_w * 0.18,  # Price
        usable_w * 0.18   # Sub
    ]

    table = Table(data, colWidths=col_w, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTNAME", (0, 1), (-1, -2), "Times-Roman"),
        ("FONTSIZE", (0, 1), (-1, -2), 6),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),

        # Merge and format the Grand Total cell
        ("SPAN", (-3, -1), (-1, -1)),
        ("BOX", (-3, -1), (-1, -1), 0.7, colors.black),
        ("FONTNAME", (-3, -1), (-3, -1), "Times-Bold"),
        ("FONTSIZE", (-3, -1), (-3, -1), 7),
        ("ALIGN", (-3, -1), (-3, -1), "RIGHT"),
    ]))
    _, table_h = table.wrap(usable_w, 1000 * mm)
    
    # 4) Terms & Conditions
    terms = [
        "Terms & Conditions",
        "1. All charges are accepted on owner’s risk.",
        "2. We are not responsible for articles taken within 40 days.",
        "3. 1/4 of the price is paid after 30 days if a claim is filed within 40 days.",
        "4. Company is not responsible for wear & tear or unremovable stains.",
        "5. Delivery after 4 days, except during monsoon.",
        "6. We are not responsible for any damage to cheap-quality sarees/dresses.",
        "Delivery will not be given without receipt.",
    ]
    term_paras = [Paragraph(t, body) for t in terms]
    terms_h = sum(p.wrap(usable_w, 1000 * mm)[1] for p in term_paras) + len(term_paras) * 2

    # 5) Vertical spacings
    pad_top = 5 * mm
    pad_bot = 25 * mm
    logo_h = 20 * mm
    logo_pad = 4 * mm
    gap = 4 * mm
    barcode_h = 12 * mm   # same as before
    bt_gap = 5 * mm
    cust_h = 3 * 4 * mm    # ~12 mm
    footer_h = 10 * mm * 1.5
    bottom_buffer = 100 * mm
    total_h = (
        pad_top
        + logo_h
        + logo_pad
        + gap
        + barcode_h
        + bt_gap
        + gap
        + cust_h
        + gap
        + table_h
        + gap
        + terms_h
        + gap
        + footer_h
        + pad_bot
        + bottom_buffer
    )

    # 6) Create the canvas
    c = canvas.Canvas(os.path.join(base_path, f"{bill_number}.pdf"), pagesize=(page_w, total_h))
    w, h = page_w, total_h
    y = h - pad_top

    # 7) Draw the logo (high‐contrast B/W)
    try:
        logo = Image.open(os.path.join(base_path, "crystal_logo.png")).convert("L")
        logo = ImageEnhance.Contrast(logo).enhance(4.0)
        logo = ImageEnhance.Brightness(logo).enhance(1.5)
        logo = logo.point(lambda p: 0 if p < 128 else 255, "1").convert("L")
        tmp_logo_path = os.path.join(base_path, f"{bill_number}_logo.png")
        logo.save(tmp_logo_path)

        lw = usable_w * 0.7
        lx = (w - lw) / 2
        c.drawImage(ImageReader(tmp_logo_path), lx, y - logo_h, lw, logo_h, mask="auto")
        os.remove(tmp_logo_path)
    except Exception:
        pass

    y -= (logo_h + logo_pad)

    # 8) Shop Address (centered, Times-Bold 8 pt; drawn twice for extra‐bold)
    c.setFillColor(colors.black)
    draw_text = c.drawCentredString
    # draw it twice, offset by 0.2 pt, to simulate darker text
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 8)
        draw_text(w / 2, y - dy, "Shop No 3, Raj Complex, Opp. Police Chowky,")
        draw_text(w / 2, y - 4 * mm - dy, "Azad Chawk, Valsad-396001")
        draw_text(w / 2, y - 8 * mm - dy, "Contact: +91 8866367144, +91 8141007111")

    rule_y = y - 10 * mm
    c.setLineWidth(0.7)
    c.line(margin, rule_y, w - margin, rule_y)
    c.setLineWidth(0.3)

    # 9) Draw the barcode (bill number) at 12 mm tall
    raw = generate_barcode(
        bill_number,
        f"{bill_number}_bill",
        display_text=None,
    )
    try:
        bar = Image.open(raw).convert("L")
        bar = ImageEnhance.Contrast(bar).enhance(4.0)
        bar = bar.point(lambda p: 0 if p < 128 else 255, "1").convert("L")
        tmpb = os.path.join(base_path, f"bills{bill_number}_bar.png")
        bar.save(tmpb)

        bw = usable_w * 0.7
        bh = barcode_h
        bt = rule_y - (4 * mm)
        bb = bt - bh

        size = min(bw, bh)  # pick the smaller of the two to ensure it's square
        c.drawImage(ImageReader(tmpb), (w - size) / 2, bb, size, size, mask="auto")

        os.remove(tmpb)
    except Exception:
        pass

    # Move “y” to 4 mm below the barcode
    y = bb - (4 * mm)

    # 10) Customer & Bill Info (everything Times-Bold / drawn twice)
    y -= gap  # 4 mm
    c.setFillColor(colors.black)

    # Draw “Customer:” label twice
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 10)
        c.drawString(margin, y - dy, "Customer:")

    label_width = c.stringWidth("Customer:", "Times-Bold", 10)
    x_for_name = margin + label_width + (2 * mm)
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 10)
        c.drawString(x_for_name, y - dy, customer_name)

    # Draw “Bill No:” right‐aligned, twice
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 10)
        c.drawRightString(w - margin, y - dy, f"Bill No: {bill_number}")

    y -= (6 * mm)  # move down ~6 mm

    # Draw “Mobile No:” label twice
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 10)
        c.drawString(margin, y - dy, "Mobile No:")

    label2_width = c.stringWidth("Mobile No:", "Times-Bold", 10)
    x_for_phone = margin + label2_width + (2 * mm)
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 10)
        c.drawString(x_for_phone, y - dy, customer_phone)
    bill_date_str = datetime.now().strftime("%d/%m/%Y %I:%M %p")
    y -= (6 * mm)  # move down ~6 mm below mobile

    for dy in (0, 0.2):
        c.setFont("Times-Bold", 10)
        c.setFillColor(colors.black)
        c.drawString(margin, y - dy, "Bill Date:")

    label3_width = c.stringWidth("Bill Date:", "Times-Bold", 10)
    x_for_date = margin + label3_width + (2 * mm)
    for dy in (0, 0.2):
        c.drawString(x_for_date, y - dy, bill_date_str)
    # 11) Draw the table just below
    y -= (8 * mm)
    c.setFillColor(colors.black)
    table.wrapOn(c, usable_w, table_h)
    table.drawOn(c, margin, y - table_h)
    

    # 12) “Delivery Date:” just below table
    y_after_table = y - table_h

    # ➕ Add “Total Units” (drawn twice for bold effect)
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 8)
        c.setFillColor(colors.black)
        c.drawString(margin, y_after_table - dy, f"Total Units: {total_units}")

    # Adjust Y below it
    y_after_table -= (5 * mm)

    # ➕ Add “Delivery Date” just below Total Units
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 8)
        c.setFillColor(colors.black)
        c.drawString(margin, y_after_table - dy, f"Delivery Date: {delivery_date}")

    # Extra spacing after delivery date
    y_after_table -= (6 * mm)
    # 13) Terms & Conditions
    y -= (table_h + gap)

    # ⬅️ Add extra space before T&Cs
    y -= 6 * mm  # add 6mm vertical space

    c.setFont("Times-Bold", 6)
    c.setFillColor(colors.black)
    for p in term_paras:
        tw, th = p.wrap(usable_w, 1000 * mm)
        p.drawOn(c, margin, y - th)
        y -= (th + 2)

    # 14) Footer (“SUNDAY CLOSED” / “THANK YOU !!! VISIT AGAIN...”)
    y -= (gap + (footer_h / 2) + (4 * mm))
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 8)
        c.setFillColor(colors.black)
        c.drawCentredString(w / 2, y - dy, "SUNDAY CLOSED")
    for dy in (0, 0.2):
        c.setFont("Times-Bold", 7)
        c.setFillColor(colors.black)
        c.drawCentredString(w / 2, y - (5 * mm) - dy, "THANK YOU !!! VISIT AGAIN...")

    # 15) Save & return
    c.save()
    return os.path.join(base_path, f"{bill_number}.pdf"), [raw]



import os
import subprocess
from tkinter import messagebox

# # adjust this path if your SumatraPDF is installed elsewhere
# SUMATRA = r"C:\Program Files\SumatraPDF\SumatraPDF.exe"

# def print_pdf_with_sumatrapdf(pdf_path, printer_name):
#     if not os.path.exists(SUMATRA):
#         messagebox.showerror("Print Error", "SumatraPDF not found at:\n" + SUMATRA)
#         return

#     try:
#         # -silent will hide dialogs, -print-to sends to the named device
#         subprocess.Popen([
#             SUMATRA,
#             "-print-to", printer_name,
#             "-silent",
#             pdf_path
#         ], shell=False)
#     except Exception as e:
#         messagebox.showerror("Print Error", f"SumatraPDF failed:\n{e}")
GS_PATH = r"C:\Program Files\gs\gs10.05.1\bin\gswin64c.exe"
DPI = 600

GS_COMMON_FLAGS = [
    "-dBATCH",
    "-dNOPAUSE",
    "-dSAFER",
    "-sDEVICE=mswinpr2",
    f"-r{DPI}",
    "-dFIXEDMEDIA",
    "-dFitPage",
    "-dNumCopies=1",
    "-dTopMargin=0"  # Add this
]

def print_bill(pdf_path):
    try:
        args = [
            GS_PATH,
            *GS_COMMON_FLAGS,
            f"-sOutputFile=%printer%{BILL_PRINTER}",
            pdf_path
        ]
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[❌] Ghostscript failed: {e}")

import os
from PIL import Image, ImageWin
import win32print, win32ui, win32con
from tkinter import messagebox

# def print_barcodes(barcode_files):
#     printer_name     = BARCODE_PRINTER

#     # Physical label/stock dims (in inches)
#     LABEL_WIDTH_IN   = 1.49
#     side_margin_in   = 0.05
#     top_margin_in    = 0.75
#     inter_gap_in     = 0.05
#     bottom_margin_in = 1.75
#     left_adjust_in   = 0.00

#     # 1) open the printer
#     try:
#         hPrinter = win32print.OpenPrinter(printer_name)
#     except Exception as e:
#         messagebox.showerror("Print Error",
#                              f"Cannot open printer '{printer_name}':\n{e}")
#         return

#     try:
#         # 2) create a DC & query its DPI (203×203 on TE244)
#         hDC = win32ui.CreateDC()
#         hDC.CreatePrinterDC(printer_name)
#         dpi_x = hDC.GetDeviceCaps(win32con.LOGPIXELSX)
#         dpi_y = hDC.GetDeviceCaps(win32con.LOGPIXELSY)

#         # 3) convert inches → device‐pixels
#         pw  = int(round(LABEL_WIDTH_IN   * dpi_x))
#         sm  = int(round(side_margin_in   * dpi_x))
#         tm  = int(round(top_margin_in    * dpi_y))
#         gp  = int(round(inter_gap_in     * dpi_y))
#         bm  = int(round(bottom_margin_in * dpi_y))
#         la  = int(round(left_adjust_in   * dpi_x))
#         bar_w = pw - 2*sm - la

#         # 4) load & preprocess each 500 dpi PNG, scaling to bar_w @ 203 dpi
#         images = []
#         for path in barcode_files:
#             if not os.path.exists(path):
#                 messagebox.showerror("Print Error",
#                                      f"Barcode file not found:\n{path}")
#                 continue

#             img = Image.open(path).convert("RGB")
#             # contrast-boost & threshold
#             img = ImageEnhance.Contrast(img).enhance(4.0)
#             img = img.convert("L").point(lambda p: 0 if p<128 else 255, "1").convert("RGB")

#             # scale: new_width = bar_w (device px),
#             #         new_height = orig_h * (bar_w / orig_w)
#             ow, oh = img.size
#             new_h = int(round(oh * (bar_w / ow)))
#             img   = img.resize((bar_w, new_h), Image.NEAREST)
#             images.append(img)

#         if not images:
#             return

#         # 5) print them
#         hDC.StartDoc("Multi-Barcode Print")
#         hDC.StartPage()

#         y = tm
#         for img in images:
#             dib = ImageWin.Dib(img)
#             x   = sm + la
#             dib.draw(hDC.GetHandleOutput(),
#                      (x, y, x + img.width, y + img.height))
#             y  += img.height + gp

#         # final bottom‐margin so footer never gets cut
#         if bm:
#             blank = Image.new("RGB", (pw, bm), "white")
#             dib   = ImageWin.Dib(blank)
#             dib.draw(hDC.GetHandleOutput(),
#                      (0, y, pw, y + bm))

#         hDC.EndPage()
#         hDC.EndDoc()
#         hDC.DeleteDC()

#     except Exception as e:
#         messagebox.showerror("Print Error",
#                              f"Failed to print barcodes:\n{e}")
#     finally:
#         win32print.ClosePrinter(hPrinter)

from PIL import Image, ImageEnhance, ImageWin
import win32print, win32ui, win32con
from tkinter import messagebox
import os

# def print_barcodes(barcode_files):
#     """
#     Print each PNG on its own 1.49"×1.97" label, with correct margins
#     and a dynamic bottom-blank so nothing ever gets cut off.
#     """
#     printer_name     = BARCODE_PRINTER

#     # physical label size (inches)
#     LABEL_W_IN       = 1.49
#     LABEL_H_IN       = 1.97
#     side_in          = 0.05
#     top_in           = 0.75
#     inter_gap_in     = 0.05
#     left_adj_in      = 0.00

#     try:
#         hPrinter = win32print.OpenPrinter(printer_name)
#     except Exception as e:
#         messagebox.showerror("Print Error", f"Cannot open printer '{printer_name}':\n{e}")
#         return

#     try:
#         # create DC & query TE244’s native DPI (~203)
#         hDC = win32ui.CreateDC()
#         hDC.CreatePrinterDC(printer_name)
#         dpi_x = hDC.GetDeviceCaps(win32con.LOGPIXELSX)
#         dpi_y = hDC.GetDeviceCaps(win32con.LOGPIXELSY)

#         # convert inches → device-pixels
#         pw  = int(round(LABEL_W_IN  * dpi_x))
#         ph  = int(round(LABEL_H_IN  * dpi_y))
#         sm  = int(round(side_in      * dpi_x))
#         tm  = int(round(top_in       * dpi_y))
#         gp  = int(round(inter_gap_in * dpi_y))
#         la  = int(round(left_adj_in  * dpi_x))
#         bar_w = pw - 2*sm - la

#         hDC.StartDoc("Itemized Barcode Print")

#         for path in barcode_files:
#             if not os.path.exists(path):
#                 messagebox.showerror("Print Error", f"File not found:\n{path}")
#                 continue

#             # — load, boost contrast & threshold —
#             img = Image.open(path).convert("RGB")
#             img = ImageEnhance.Contrast(img).enhance(4.0)
#             img = img.convert("L").point(lambda p: 0 if p<128 else 255, "1").convert("RGB")

#             # — scale to fit printable width, keep aspect ratio —
#             ow, oh = img.size
#             nh     = int(round(oh * (bar_w / ow)))
#             img    = img.resize((bar_w, nh), Image.NEAREST)

#             # — start a new label (page) —
#             hDC.StartPage()

#             # draw barcode at top margin
#             y = tm
#             dib = ImageWin.Dib(img)
#             x  = sm + la
#             dib.draw(hDC.GetHandleOutput(), (x, y, x + img.width, y + img.height))

#             # calculate remaining blank below to avoid cut-off
#             used_h = y + img.height
#             blank_h = ph - used_h
#             if blank_h > 0:
#                 blank = Image.new("RGB", (pw, blank_h), "white")
#                 dib2  = ImageWin.Dib(blank)
#                 dib2.draw(hDC.GetHandleOutput(), (0, used_h, pw, used_h + blank_h))

#             hDC.EndPage()
#             img.close()

#         hDC.EndDoc()
#         hDC.DeleteDC()

#     except Exception as e:
#         messagebox.showerror("Print Error", f"Failed to print barcodes:\n{e}")
#     finally:
#         win32print.ClosePrinter(hPrinter)

from PIL import Image, ImageEnhance, ImageWin, ImageDraw
import win32print, win32ui, win32con
import threading, os

from PIL import Image, ImageEnhance, ImageWin
import win32print, win32ui, win32con
import threading, os

# ─── Settings ─────────────────────────────────────────────
DPI = 203
GAP_CM = 15               # 4 cm after each barcode
FINAL_FEED_CM = 30       # 10 cm after the last barcode
GAP_DOTS = int(GAP_CM * 8)                 # TSC uses 8 dots/mm
FINAL_FEED_DOTS = int(FINAL_FEED_CM * 8)   # Final feed
CONTRAST_FACTOR = 4.0
LEFT_SHIFT_PIXELS = 0
TSC_PRINTER_NAME = "TSC TE244"             # Replace with your printer name

# ─── Main Function ────────────────────────────────────────
def print_barcodes(barcode_files):
    def worker():
        try:
            hPrinter = win32print.OpenPrinter(TSC_PRINTER_NAME)
        except Exception as e:
            print(f"[❌] Could not open TSC printer: {e}")
            return

        printable_w = printable_h = offset_x = offset_y = None

        for i, path in enumerate(barcode_files):
            if not os.path.exists(path):
                print(f"[!] File not found: {path}")
                continue

            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(TSC_PRINTER_NAME)

            if printable_w is None:
                printable_w = hDC.GetDeviceCaps(win32con.HORZRES)
                printable_h = hDC.GetDeviceCaps(win32con.VERTRES)
                offset_x = hDC.GetDeviceCaps(win32con.PHYSICALOFFSETX)
                offset_y = hDC.GetDeviceCaps(win32con.PHYSICALOFFSETY)

            # ─── Prepare Image ───
            img = Image.open(path).convert("RGB")
            img = ImageEnhance.Contrast(img).enhance(CONTRAST_FACTOR)
            ow, oh = img.size
            scale = min(printable_w / ow, printable_h / oh)
            nw, nh = int(ow * scale), int(oh * scale)
            img = img.resize((nw, nh), Image.NEAREST)
            canvas = Image.new("RGB", (nw, nh), "white")
            canvas.paste(img, (0, 0))
            dib = ImageWin.Dib(canvas)

            try:
                # ─── 1. Print Barcode ───
                hDC.StartDoc(f"Barcode {i+1}")
                hDC.StartPage()
                x = offset_x + (printable_w - nw) // 2 - LEFT_SHIFT_PIXELS
                y = offset_y + (printable_h - nh) // 2
                dib.draw(hDC.GetHandleOutput(), (x, y, x + nw, y + nh))
                hDC.EndPage()
                hDC.EndDoc()
                hDC.DeleteDC()

                # ─── 2. Feed 4cm After Barcode ───
                tspl_feed = f"FEED {GAP_DOTS}\r\n".encode('ascii')
                job = win32print.StartDocPrinter(hPrinter, 1, ("GapFeed", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, tspl_feed)
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)

                print(f"[🖨️] Printed {os.path.basename(path)} + 4cm feed")

            except Exception as e:
                print(f"[❌] Error printing {path}: {e}")
                try: hDC.DeleteDC()
                except: pass

        # ─── 3. Final Feed of 10cm ───
        tspl_final_feed = f"FEED {FINAL_FEED_DOTS}\r\n".encode('ascii')
        job = win32print.StartDocPrinter(hPrinter, 1, ("FinalFeed", None, "RAW"))
        win32print.StartPagePrinter(hPrinter)
        win32print.WritePrinter(hPrinter, tspl_final_feed)
        win32print.EndPagePrinter(hPrinter)
        win32print.EndDocPrinter(hPrinter)

        print(f"[📦] Final 10cm feed issued after last barcode.")

        win32print.ClosePrinter(hPrinter)

    threading.Thread(target=worker).start()
# def print_barcodes(barcode_files):
#     """
#     Print each image file via Ghostscript at high resolution + antialiasing.
#     """
#     for path in barcode_files:
#         if not os.path.exists(path):
#             messagebox.showerror("Print Error", f"File not found:\n{path}")
#             continue

#         args = [
#             GS_PATH,
#             *GS_COMMON_FLAGS,
#             f"-sOutputFile=%printer%{BARCODE_PRINTER}",
#             path
#         ]
#         try:
#             # use Popen if you don't want to block on each print
#             subprocess.run(args, check=True)
#         except subprocess.CalledProcessError as e:
#             messagebox.showerror("Print Error", f"Failed to print {os.path.basename(path)}:\n{e}")

                                        
def send_whatsapp_message(mobile, pdf_path, customer_name, total_amount, bill_number):
    """Send the bill PDF via WhatsApp with bill number and amount."""
    message = (
        f"Dear {customer_name},\n"
        f"Thank you for choosing Crystal Cleaners.\n"
        f"Your bill number is {bill_number} and the amount is ₹{total_amount:.2f}.\n"
        f"Please find the attached bill.\n"
        f"We appreciate your business!"
    )
    data = {"phone": mobile, "message": message, "pdfPath": pdf_path}
    try:
        resp = requests.post(WHATSAPP_SERVER_URL, json=data)
        if resp.status_code == 200:
            messagebox.showinfo("Success", "Bill sent via WhatsApp!")
        else:
            messagebox.showerror("Error", f"WhatsApp send failed:\n{resp.text}")
    except Exception as e:
        messagebox.showerror("Error", str(e))

class AutocompleteCombobox(ttk.Combobox):
    """A ttk.Combobox with drop-down list filtered as you type (substring match)."""
    def __init__(self, master=None, completevalues=None, **kwargs):
        self._completion_list = sorted(completevalues or [], key=str.lower)
        super().__init__(master, values=self._completion_list, **kwargs)

        self.bind('<KeyRelease>', self._on_keyrelease)
        self.bind('<Button-1>', self._on_arrow_click)

    def set_completion_list(self, completion_list):
        self._completion_list = sorted(completion_list or [], key=str.lower)
        self.configure(values=self._completion_list)

    def _on_arrow_click(self, event):
        # show full list only if empty or user clicked to expand
        if not self.get():
            self.configure(values=self._completion_list)
        # open dropdown and focus entry box
        self.after_idle(lambda: (
            self.event_generate('<Down>'),
            self.focus_set(),
            self.icursor(len(self.get()))
        ))

    def _autocomplete(self):
        """Filter the drop-down list without disturbing typing focus."""
        typed = self.get()
        if not typed:
            self.configure(values=self._completion_list)
            return

        filtered = [item for item in self._completion_list if typed.lower() in item.lower()]
        self.configure(values=filtered)

    def _on_keyrelease(self, event):
        if event.keysym in ('BackSpace', 'Left', 'Right', 'Down', 'Up', 'Return', 'Escape', 'Tab'):
            return
        self._autocomplete()
        
class BillingApp:
    def __init__(self, root):
        start_node_server()
        self.root = root
        self.root.title("Laundry Billing and Barcode Tagging System")
        self.root.geometry("1024x768")
        self.root.attributes("-fullscreen", True)

        # ————— Modern ttk theme —————
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f0f0f0")
        style.configure("TLabel", background="#f0f0f0", font=("Segoe UI", 11))
        style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("TButton", font=("Segoe UI", 11), padding=6)
        
        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(anchor="ne", padx=10, pady=10)
        ttk.Button(ctrl_frame, text="✕", width=2,
                command=self.root.quit).pack(side="right")
        # ————— Menu bar —————

        # minimize
        ttk.Button(ctrl_frame, text="-", width=2,
                command=self.root.iconify).pack(side="right", padx=(0,5))
        # exit
        
        
        

        # ————— Header —————
        header = ttk.Label(self.root, text="Laundry Billing and Barcode Tagging System", style="Header.TLabel")
        header.pack(fill="x", pady=(10, 20))

        self.conn = sqlite3.connect(DATABASE)
        self.cursor = self.conn.cursor()
        self.cart = []
        self.grand_total = 0
        
        self.subtotal_var = tk.DoubleVar(value=0.0)
        self.discount_amount_var = tk.DoubleVar(value=0.0)
        self.discount_percent_var = tk.DoubleVar(value=0.0)
        self.advance_var = tk.DoubleVar(value=0.0)
        self.grand_total_var = tk.DoubleVar(value=0.0)
        self.total_items_var  = tk.IntVar(value=0)
        self.paymode_var = tk.StringVar(value="Cash")

        self.create_login_frame()

    def exit_fullscreen(self, event=None):
        self.root.attributes("-fullscreen", False)

    def create_login_frame(self):
        self.login_frame = ttk.Frame(self.root)
        self.login_frame.pack(padx=20, pady=20)

        ttk.Label(self.login_frame, text="Username").pack(anchor="w")
        self.username_var = tk.StringVar()
        ttk.Entry(self.login_frame, textvariable=self.username_var).pack(fill="x", pady=5)

        ttk.Label(self.login_frame, text="Password").pack(anchor="w")
        self.password_var = tk.StringVar()
        ttk.Entry(self.login_frame, textvariable=self.password_var, show="*").pack(fill="x", pady=5)

        ttk.Button(self.login_frame, text="Login", command=self.login).pack(pady=10)

    def login(self):
        if self.username_var.get()=="0024" and self.password_var.get()=="0024":
            self.login_frame.destroy()
            self.build_billing_system()
        else:
            messagebox.showerror("Login Failed", "Invalid credentials")

    def build_billing_system(self):
        action_frame = ttk.Frame(self.root)
        action_frame.pack(padx=20, pady=10, fill="x")

        ttk.Button(action_frame, text="Show All Orders",   command=self.show_orders).grid(row=0,column=0,padx=5)
        ttk.Button(action_frame, text="Date Wise Orders",   command=self.show_date_wise_orders).grid(row=0,column=1,padx=5)
        ttk.Button(action_frame, text="Ready Items", command=self.open_ready_window).grid(row=0,column=2,padx=5)

        ttk.Button(action_frame, text="Search by Mobile",   command=self.show_orders_by_mobile).grid(row=0,column=3,padx=5)
        ttk.Button(action_frame, text="Old Data", command=self.show_old_data).grid(row=0,column=4,padx=5)
        ttk.Button(action_frame, text="Daily Register", command=self.show_daily_register).grid(row=0, column=5, padx=5)
        ttk.Button(action_frame, text="Add Product",     command=lambda: self.add_product_or_service("Product")).grid(row=0,column=6,padx=5)
        ttk.Button(action_frame, text="Add Service",     command=lambda: self.add_product_or_service("Service")).grid(row=0,column=7,padx=5)
        ttk.Button(action_frame, text="Edit Products", command=lambda: self.edit_item_or_service("Product")).grid(row=0, column=8, padx=5)
        ttk.Button(action_frame, text="Edit Services", command=lambda: self.edit_item_or_service("Service")).grid(row=0, column=9, padx=5)
        # ttk.Button(action_frame, text="Edit Prices", command=self.edit_item_prices).grid(row=0,column=5,padx=5)
            # inside build_billing_system(), in the action_frame
        self.create_customer_section()
        self.create_cart_section()
        self.create_action_buttons()

    def create_customer_section(self):
        self.customer_frame = ttk.Frame(self.root)
        self.customer_frame.pack(padx=20, pady=10, fill="x")

        ttk.Label(self.customer_frame, text="Name:").grid(row=0,column=0, padx=5, pady=5, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(self.customer_frame, textvariable=self.name_var, width=30).grid(row=0,column=1, padx=5)

        ttk.Label(self.customer_frame, text="Phone:").grid(row=0,column=2, padx=5)
        self.phone_var = tk.StringVar()
        ttk.Entry(self.customer_frame, textvariable=self.phone_var, width=30 ).grid(row=0,column=3, padx=5)

        ttk.Button(self.customer_frame, text="Search", command=self.search_customer).grid(row=0,column=4, padx=5)
        self.cursor.execute("SELECT bill_number FROM bills ORDER BY id DESC LIMIT 1")
        row = self.cursor.fetchone()
        last_bn = row[0] if row else "—"

        # Show last bill number as a label on the right side of action_frame
        self.last_bill_label = ttk.Label(self.customer_frame, text=f"Last Bill No : {last_bn}", font=("Segoe UI", 15, "bold"))
        self.last_bill_label.grid(row=0, column=20, padx=10, sticky="e")

    def fetch_products(self):
        self.cursor.execute("SELECT item_name FROM itemlist ORDER BY item_name COLLATE NOCASE")
        return [r[0] for r in self.cursor.fetchall()]

    def fetch_services(self):
        self.cursor.execute("SELECT service_name FROM servicelist ORDER BY service_name COLLATE NOCASE")
        return [r[0] for r in self.cursor.fetchall()]

    def edit_item_prices(self):
        win = tk.Toplevel(self.root)
        win.title("Edit Item Prices")
        win.geometry("400x500")

        # Treeview for items
        cols = ("ID","Name","Price")
        tr = ttk.Treeview(win, columns=cols, show="headings", height=15)
        for c in cols:
            tr.heading(c, text=c)
            tr.column(c, anchor="center")
        tr.pack(fill="both", expand=True, padx=10, pady=10)

        # load data
        self.cursor.execute("SELECT id, item_name, price FROM itemlist ORDER BY item_name")
        for row in self.cursor.fetchall():
            tr.insert("", "end", values=row)

        # Editor frame
        frm = ttk.Frame(win)
        frm.pack(fill="x", padx=10, pady=5)
        ttk.Label(frm, text="New Price:").grid(row=0,column=0, sticky="e")
        price_var = tk.StringVar()
        ent = ttk.Entry(frm, textvariable=price_var, width=10)
        ent.grid(row=0,column=1, padx=5)

        def on_select(event):
            sel = tr.selection()
            if not sel: return
            pid,name,pr = tr.item(sel[0])["values"]
            price_var.set(f"{pr:.2f}")
        tr.bind("<<TreeviewSelect>>", on_select)

        def save_price():
            sel = tr.selection()
            if not sel:
                messagebox.showerror("Error","Select an item first"); return
            pid = tr.item(sel[0])["values"][0]
            try:
                newp = float(price_var.get())
            except:
                messagebox.showerror("Error","Invalid price"); return
            self.cursor.execute("UPDATE itemlist SET price=? WHERE id=?", (newp, pid))
            self.conn.commit()
            tr.item(sel[0], values=(pid, tr.item(sel[0])["values"][1], newp))
            messagebox.showinfo("Saved","Price updated")

        ttk.Button(win, text="Save Price", command=save_price).pack(pady=(0,10))
    def on_product_select(self, event=None):
        name = self.product_var.get().strip()
        if not name:
            return
        # fetch price from itemlist
        self.cursor.execute(
            "SELECT price FROM itemlist WHERE item_name = ?",
            (name,)
        )
        row = self.cursor.fetchone()
        if row and row[0] is not None:
            # price_var is a StringVar
            self.price_var.set(f"{row[0]:.2f}")
            
    def create_cart_section(self):
        self.cart_frame = ttk.Frame(self.root)
        self.cart_frame.pack(padx=20, pady=10, fill="x")

        # Product & Service selection
        # ── Product Dropdown ─────────────────────────────────────
        ttk.Label(self.cart_frame, text="Product Name:").grid(row=0, column=0, padx=5, pady=5)
        self.product_var = tk.StringVar()
        self.product_dropdown = AutocompleteCombobox(
            self.cart_frame,
            textvariable=self.product_var,
            width=60
        )
        self.product_dropdown.set_completion_list(self.fetch_products())
        self.product_dropdown.grid(row=0, column=1, padx=5)
        self.product_dropdown.bind("<<ComboboxSelected>>", self.on_product_select)

        # ── Service Dropdown ─────────────────────────────────────
        ttk.Label(self.cart_frame, text="Service Name:").grid(row=0, column=2, padx=5)
        self.service_var = tk.StringVar()
        self.service_dropdown = AutocompleteCombobox(
            self.cart_frame,
            textvariable=self.service_var,
            width=40
        )
        self.service_dropdown.set_completion_list(self.fetch_services())
        self.service_dropdown.grid(row=0, column=3, padx=5)

        # Price & Quantity
        ttk.Label(self.cart_frame, text="Price:").grid(row=1, column=0, padx=5)
        self.price_var = tk.StringVar()
        ttk.Entry(self.cart_frame, textvariable=self.price_var).grid(row=1, column=1, padx=5)

        ttk.Label(self.cart_frame, text="Quantity:").grid(row=1, column=2, padx=5)
        self.quantity_var = tk.StringVar()
        ttk.Entry(self.cart_frame, textvariable=self.quantity_var).grid(row=1, column=3, padx=5)

        # Add to cart button
        ttk.Button(self.cart_frame, text="Add to Cart", command=self.add_to_cart).grid(row=1, column=4, padx=5)

        # Cart display
        style = ttk.Style()
        style.configure("Treeview", rowheight=30)
        self.cart_tree = ttk.Treeview(self.root, columns=("Product","Service","Price","Qty","Units","Total"), show="headings")
        for col in ("Product","Service","Price","Qty","Units","Total"):
            self.cart_tree.heading(col, text=col)
            if col == "Product":
                self.cart_tree.column(col, anchor="center", width=350)  # Wider + left-aligned
            elif col == "Service":
                self.cart_tree.column(col, anchor="center", width=180)
            elif col == "Price":
                self.cart_tree.column(col, anchor="center", width=80)
            elif col == "Qty":
                self.cart_tree.column(col, anchor="center", width=60)
            elif col == "Units":
                self.cart_tree.column(col, anchor="center", width=60)
            elif col == "Total":
                self.cart_tree.column(col, anchor="center", width=100)
        self.cart_tree.heading("Units", text="Units")
        self.cart_tree.column("Units", anchor="center")
        self.cart_tree.bind("<Double-1>", self.edit_cart_item)
        self.cart_tree.pack(padx=20, pady=10, fill="both", expand=True)

        totals_frame = ttk.Frame(self.root)
        sub_frame = ttk.Frame(self.root)
        sub_frame.pack(padx=20, pady=(0,5), fill="x")
        ttk.Label(totals_frame, text="Total Items: ", font=("Segoe UI", 12)).pack(side="left", padx=(20,0))
        ttk.Label(totals_frame, textvariable=self.total_items_var, font=("Segoe UI", 12, 'bold')).pack(side="left")
        totals_frame.pack(padx=20, pady=(0,5), fill="x")

        # Controls: discount, percent, advance, payment mode
        controls = ttk.Frame(self.root)
        controls.pack(padx=20, pady=(0,10), fill="x")

        ttk.Label(controls, text="Discount (₹):").grid(row=0, column=0, sticky="e")
        ttk.Entry(controls, textvariable=self.discount_amount_var, width=10).grid(row=0, column=1, padx=(0,10))
        self.discount_amount_var.trace_add("write", lambda *args: self.update_grand_total())

        ttk.Label(controls, text="Discount (%):").grid(row=0, column=2, sticky="e")
        ttk.Entry(controls, textvariable=self.discount_percent_var, width=10).grid(row=0, column=3, padx=(0,10))
        self.discount_percent_var.trace_add("write", lambda *args: self.apply_discount_percent())

        ttk.Label(controls, text="Advance (₹):").grid(row=0, column=4, sticky="e")
        ttk.Entry(controls, textvariable=self.advance_var, width=10).grid(row=0, column=5, padx=(0,10))
        self.advance_var.trace_add("write", lambda *args: self.update_grand_total())


        # Grand total display
        gt_frame = ttk.Frame(self.root)
        gt_frame.pack(padx=20, pady=(0,10), fill="x")
        ttk.Label(gt_frame, text="Grand Total: ", font=("Segoe UI", 14)).pack(side="left")
        ttk.Label(gt_frame, textvariable=self.grand_total_var, font=("Segoe UI", 14, 'bold')).pack(side="left")
    
    def edit_cart_item(self, event):
        """Load the selected cart row back into the entry fields for editing."""
        sel = self.cart_tree.selection()
        if not sel:
            return

        # The Treeview has six columns: Product, Service, Price, Qty, Units, Total
        prod, srv, price, qty, units, total = self.cart_tree.item(sel[0])["values"]

        # Populate the entry widgets with those six values
        self.product_var.set(prod)
        self.service_var.set(srv)
        self.price_var.set(str(price))
        self.quantity_var.set(str(qty))

        # Remove exactly this tuple from the internal self.cart list.
        # self.cart entries are stored as (product, service, price, qty, units, total).
        try:
            self.cart.remove((prod, srv, float(price), int(qty), int(units), float(total)))
        except ValueError:
            # If for some reason it cannot find that exact tuple, just pass.
            pass

        # Remove the item from the Treeview itself
        self.cart_tree.delete(sel[0])

        # Re‐compute subtotal / grand total / total‐items based on the new self.cart
        self.update_subtotal()
        self.update_grand_total()
        self.update_total_items()

   
    def apply_discount_percent(self):
        try:
            pct = self.discount_percent_var.get()
            sub = self.subtotal_var.get()
            amt = (pct / 100.0) * sub
            traces = self.discount_amount_var.trace_info()
            if traces:
                self.discount_amount_var.trace_remove('write', traces[0][1])
            self.discount_amount_var.set(round(amt, 2))
            self.discount_amount_var.trace_add('write', lambda *args: self.update_grand_total())
            self.update_grand_total()
        except:
            pass

    def update_grand_total(self):
        sub = self.subtotal_var.get()
        disc = self.discount_amount_var.get()
        adv = self.advance_var.get()
        total = sub - disc - adv
        self.grand_total_var.set(round(max(total, 0), 2))

        
    def create_action_buttons(self):
        action_frame = ttk.Frame(self.root)
        action_frame.pack(padx=20, pady=10, fill="x")

        # Center-aligned sub-frame inside action_frame
        center_frame = ttk.Frame(action_frame)
        center_frame.pack(anchor="center")

        # Green style for Generate Bill
        style = ttk.Style()
        style.configure("Green.TButton", foreground="white", background="green")
        style.map("Green.TButton", background=[("active", "#228B22")])  # dark green on hover

        # Remove Item button
        ttk.Button(center_frame, text="Remove Item", command=self.remove_from_cart).pack(side="left", padx=10)

        # Generate Bill button with green style
        ttk.Button(center_frame, text="Generate Bill", command=self.generate_bill, style="Green.TButton").pack(side="left", padx=10)
    

    def search_customer(self):
        name_input = self.name_var.get().strip()
        phone_input = self.phone_var.get().strip()

        if phone_input:
            # lookup by mobile → populate name
            self.cursor.execute(
                "SELECT name FROM customerentry WHERE mobile = ?",
                (phone_input,)
            )
            row = self.cursor.fetchone()
            if row:
                self.name_var.set(row[0])
            else:
                messagebox.showinfo("Not found", f"No customer with phone '{phone_input}' found.")

        elif name_input:
            # lookup by name prefix → populate phone and full name
            self.cursor.execute(
                "SELECT name, mobile FROM customerentry WHERE name LIKE ? COLLATE NOCASE",
                (name_input + "%",)
            )
            row = self.cursor.fetchone()
            if row:
                full_name, mobile = row
                self.name_var.set(full_name)
                self.phone_var.set(mobile)
            else:
                messagebox.showinfo("Not found", f"No customer starting with '{name_input}' found.")

        else:
            messagebox.showerror("Error", "Enter either Name or Phone to search.")
            # insert new customer
            try:
                self.cursor.execute(
                    "INSERT INTO customerentry(name,mobile) VALUES(?,?)",
                    (name_input, phone_input)
                )
                self.conn.commit()
            except Exception as e:
                messagebox.showerror(
                    "Error saving new customer",
                    str(e)
                )
                return

            messagebox.showinfo(
                "Success",
                f"Added new customer “{name_input}” with phone {phone_input}."
            )
    def refresh_cart(self):
        """Rebuild the cart_tree from self.cart."""
        # clear existing rows
        self.cart_tree.delete(*self.cart_tree.get_children())
        # re‑insert from self.cart
        for product, service, price, qty, units, total in self.cart:
            self.cart_tree.insert("", "end", values=(product, service, price, qty, units, total))
        self.update_total_items()
            
    def add_to_cart(self):
        # retrieve and validate inputs
        try:
            if self.price_var.get().strip() == "":
                self.cursor.execute(
                    "SELECT price FROM itemlist WHERE item_name=?", 
                    (self.product_var.get().strip(),)
                )
                row = self.cursor.fetchone()
                price = float(row[0]) if row else 0.0
            else:
                price = float(self.price_var.get())
            qty = int(self.quantity_var.get())
        except:
            messagebox.showerror("Error","Invalid price or qty.")
            return

        product = self.product_var.get().strip()
        service = self.service_var.get().strip()
        if not product or not service:
            messagebox.showerror("Error","Select product and service.")
            return

        import re
        m = re.search(r'(\d+)\s*pc', product, re.IGNORECASE)
        pcs = int(m.group(1)) if m else 1
        units = pcs * qty
        total = price * qty
        self.cart.append((product, service, price, qty, units, total))
        self.cart_tree.insert("", "end", values=(product, service, price, qty, units, total))
        self.refresh_cart()
        # clear input fields
        self.product_var.set("")
        self.service_var.set("")
        self.price_var.set("")
        self.quantity_var.set("")
        # force the Treeview to refresh immediately
        self.cart_tree.update_idletasks()
        self.update_subtotal()
        self.update_grand_total()

    def update_subtotal(self):
        sub = 0.0
        for child in self.cart_tree.get_children():
            val = self.cart_tree.item(child)["values"][5]
            try:
                sub += float(val)
            except:
                pass
        self.subtotal_var.set(round(sub, 2))
        
    def update_total_items(self):
        total_units = 0
        for iid in self.cart_tree.get_children():
            vals = self.cart_tree.item(iid)["values"]
            total_units += int(vals[4])   # Units is at index 4
        self.total_items_var.set(total_units)
        
    def remove_from_cart(self):
        for sel in self.cart_tree.selection():
            vals = self.cart_tree.item(sel)["values"]
            # Ensure numeric subtraction by converting to float
            total_val = float(vals[5])
            self.grand_total -= total_val
            # Remove matching cart entries
            self.cart = [c for c in self.cart if float(c[5]) != total_val]
            self.cart_tree.delete(sel)
        self.update_subtotal()
        self.update_grand_total()
        self.update_total_items()
        
    def add_product_or_service(self, category):
        def save_entry():
            try:
                new_id = int(id_var.get().strip())
            except ValueError:
                messagebox.showerror("Error", "ID must be an integer!")
                return

            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Error", "Name is required!")
                return

            # For services, allow blank price (defaults to 0)
            try:
                if category == "Service" and price_var.get().strip() == "":
                    price = 0.0
                else:
                    price = float(price_var.get().strip())
            except ValueError:
                messagebox.showerror("Error", "Price must be a number!")
                return

            try:
                if category == "Product":
                    self.cursor.execute(
                        "INSERT INTO itemlist (id, item_name, price) VALUES (?, ?, ?)",
                        (new_id, name, price)
                    )
                else:
                    self.cursor.execute(
                        "INSERT INTO servicelist (service_id, service_name, price) VALUES (?, ?, ?)",
                        (new_id, name, price)
                    )
                self.conn.commit()

                self.product_dropdown.set_completion_list(self.fetch_products())
                self.service_dropdown.set_completion_list(self.fetch_services())

                messagebox.showinfo("Success", f"{category} added successfully.")
                popup.destroy()
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", f"ID {new_id} already exists!")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        # ───── Popup UI ─────
        popup = tk.Toplevel(self.root)
        popup.title(f"Add New {category}")
        popup.geometry("800x600")

        tk.Label(popup, text="ID:", font=("Arial", 12)).pack(pady=(10, 0))
        id_var = tk.StringVar()
        tk.Entry(popup, textvariable=id_var, font=("Arial", 12)).pack(pady=5)

        tk.Label(popup, text="Name:", font=("Arial", 12)).pack()
        name_var = tk.StringVar()
        tk.Entry(popup, textvariable=name_var, font=("Arial", 12)).pack(pady=5)

        price_var = tk.StringVar()
        if category == "Product":
            tk.Label(popup, text="Price (₹):", font=("Arial", 12)).pack()
            tk.Entry(popup, textvariable=price_var, font=("Arial", 12)).pack(pady=5)
        else:
            price_var.set("")

        tk.Button(popup, text="Save", command=save_entry, font=("Arial", 12)).pack(pady=10)

    def edit_item_or_service(self, category):
        win = tk.Toplevel(self.root)
        win.title(f"Edit {category}s")
        win.state("zoomed")
        win.transient(self.root)  # optional: keep above root
        win.focus_set()           # optional: bring to front
        win.grab_set()

        ttk.Label(win, text=f"{category}s", font=("Segoe UI", 14, "bold")).pack(pady=10)

        cols = ("ID", "Name", "Price")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        if category == "Product":
            self.cursor.execute("SELECT id, item_name, price FROM itemlist ORDER BY item_name")
        else:
            self.cursor.execute("SELECT service_id, service_name, price FROM servicelist ORDER BY service_name")

        for row in self.cursor.fetchall():
            tree.insert("", "end", values=row)

        frm = ttk.Frame(win)
        frm.pack(pady=10)
        id_var = tk.StringVar()
        name_var = tk.StringVar()
        price_var = tk.StringVar()

        ttk.Label(frm, text="ID:").grid(row=0, column=0)
        ttk.Entry(frm, textvariable=id_var, width=10, state="readonly").grid(row=0, column=1, padx=5)

        ttk.Label(frm, text="Name:").grid(row=0, column=2)
        ttk.Entry(frm, textvariable=name_var, width=20).grid(row=0, column=3, padx=5)

        ttk.Label(frm, text="Price:").grid(row=0, column=4)
        ttk.Entry(frm, textvariable=price_var, width=10).grid(row=0, column=5, padx=5)

        def on_select(event):
            sel = tree.selection()
            if not sel:
                return
            vals = tree.item(sel[0])["values"]
            id_var.set(vals[0])
            name_var.set(vals[1])
            price_var.set(f"{vals[2]:.2f}")

        tree.bind("<<TreeviewSelect>>", on_select)

        def save():
            try:
                _id = int(id_var.get())
                name = name_var.get().strip()
                if category == "Service" and price_var.get().strip() == "":
                    price = 0.0
                else:
                    price = float(price_var.get().strip())
            except Exception:
                messagebox.showerror("Error", "Invalid name or price.")
                return

            try:
                if category == "Product":
                    self.cursor.execute("UPDATE itemlist SET item_name=?, price=? WHERE id=?", (name, price, _id))
                else:
                    self.cursor.execute("UPDATE servicelist SET service_name=?, price=? WHERE service_id=?", (name, price, _id))
                self.conn.commit()
                messagebox.showinfo("Saved", f"{category} updated.")

                tree.delete(*tree.get_children())
                if category == "Product":
                    self.cursor.execute("SELECT id, item_name, price FROM itemlist ORDER BY item_name")
                else:
                    self.cursor.execute("SELECT service_id, service_name, price FROM servicelist ORDER BY service_name")
                for row in self.cursor.fetchall():
                    tree.insert("", "end", values=row)

                self.product_dropdown.set_completion_list(self.fetch_products())
                self.service_dropdown.set_completion_list(self.fetch_services())
            except Exception as e:
                messagebox.showerror("DB Error", str(e))

        def delete():
            _id = id_var.get()
            if not _id:
                return
            if not messagebox.askyesno("Confirm", f"Delete this {category.lower()}?"):
                return
            try:
                if category == "Product":
                    self.cursor.execute("DELETE FROM itemlist WHERE id=?", (_id,))
                else:
                    self.cursor.execute("DELETE FROM servicelist WHERE service_id=?", (_id,))
                self.conn.commit()
                messagebox.showinfo("Deleted", f"{category} deleted.")

                tree.delete(*tree.get_children())
                if category == "Product":
                    self.cursor.execute("SELECT id, item_name, price FROM itemlist ORDER BY item_name")
                else:
                    self.cursor.execute("SELECT service_id, service_name, price FROM servicelist ORDER BY service_name")
                for row in self.cursor.fetchall():
                    tree.insert("", "end", values=row)

                id_var.set(""); name_var.set(""); price_var.set("")
                self.product_dropdown.set_completion_list(self.fetch_products())
                self.service_dropdown.set_completion_list(self.fetch_services())
            except Exception as e:
                messagebox.showerror("Error", str(e))

        btn_frame = ttk.Frame(win)
        btn_frame.pack()
        ttk.Button(btn_frame, text="Save Changes", command=save).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="Delete", command=delete).pack(side="left", padx=10)

    def generate_bill(self):
        name = self.name_var.get().strip()
        phone = self.phone_var.get().strip()
        if not name or not phone or not self.cart:
            messagebox.showerror("Error", "Provide customer + cart.")
            return

        # Ensure customer exists
        self.cursor.execute(
            "INSERT OR IGNORE INTO customerentry(name,mobile) VALUES(?,?)",
            (name, phone)
        )
        self.conn.commit()
        self.cursor.execute(
            "SELECT id FROM customerentry WHERE mobile = ?",
            (phone,)
        )
        cid = self.cursor.fetchone()[0]

        # Payment mode booleans
        is_cash = 0
        is_gpay = 0
        is_indusind_bank = 0

        total = self.subtotal_var.get()

        # Preserve original bill-number logic
        self.cursor.execute("SELECT COUNT(*) FROM bills")
        existing = self.cursor.fetchone()[0]
        seq = 1590 + existing
        bn = f"{seq}"
        bd = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Build a list of dicts from self.cart, each with a "ready": False field
        # self.cart is a list of: [(product, service, price, qty, units, total_amt), …]
        cart_items_with_ready = []
        for (prod, srv, price, qty, units, total_amt) in self.cart:
            cart_items_with_ready.append({
                "product": prod,
                "service": srv,
                "price": price,
                "qty": qty,
                "units": units,
                "total_amt": total_amt,
                "ready": False
            })

        details_json = json.dumps(cart_items_with_ready)

        # Insert into bills, but store JSON-of-dicts in the details column
        self.cursor.execute(
            "INSERT INTO bills(customer_id, bill_number, total_amount, details, bill_date, is_cash, is_gpay, is_indusind_bank) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (cid, bn, total, details_json, bd, is_cash, is_gpay, is_indusind_bank)
        )
        self.conn.commit()

        # Generate PDF and barcodes as before
        pdf, bcodes = generate_bill_pdf(
            name,
            phone,
            details_json,
            total,
            bn,
            self.cart,
            self.discount_amount_var.get(),
            self.advance_var.get(),
            self.paymode_var.get()
        )

        # Build the item_barcodes list, one distinct code per ordered unit
        import re
        piece_pattern = re.compile(r'(\d+)\s*(?:pc|pcs|piece|pieces)\b', re.IGNORECASE)

        item_barcodes = []
        for product, service, price, qty, units, total_amt in self.cart:
            if service.strip().lower() == "steam press":
                continue

            # 1) Look up the item’s numeric ID from the itemlist table:
            self.cursor.execute("SELECT id FROM itemlist WHERE item_name = ?", (product,))
            row = self.cursor.fetchone()
            if not row:
                # If for some reason the item name isn’t found, fall back to product itself
                item_id = product.replace(" ", "_")
            else:
                item_id = str(row[0])

            # 2) Determine how many “pieces” (pcs) each unit represents:
            m = piece_pattern.search(product)
            pcs = int(m.group(1)) if m else 1
            total_pieces = units

            # 3) For each piece, encode only the numeric ID (plus bill# and sequence) as “data.”
            for i in range(total_pieces):
                # e.g. “<bill#>_<item_id>_<seq>”
                data_payload = f"{bn}_{item_id}_{i+1}"

                # 4) But still show the human‐readable item name + customer under the bars:
                footer_text = f"{name} | {product} | {service}"
                filename = f"{bn}_{item_id}_{i+1}"

                path = generate_barcode(
                    data=data_payload,
                    filename_prefix=filename,
                    display_text=footer_text, # item name + customer
                    target_mm_width=40,         # always 40 mm wide
                    dpi=203                     # 203 dpi for a 203×203 print
                )
                item_barcodes.append(path)

        # Save the PDF path & updated cart_data back into bills
        self.cursor.execute(
            "UPDATE bills SET pdf_path = ?, cart_data = ? WHERE bill_number = ?",
            (pdf, json.dumps(cart_items_with_ready), bn)
        )
        self.conn.commit()

        # Printing & WhatsApp path = generate_barcode(code, f"{bn}_{product}_{i + 1}", customer_name=name)
        try:
            print_bill(pdf)                 # Prints the bill PDF
            print_barcodes(item_barcodes)   # Prints only the item barcodes
            send_whatsapp_message(phone, pdf, name, total, bn)
        except Exception as e:
            messagebox.showerror("Error during print/WhatsApp", str(e))

        # Cleanup generated files
        if os.path.exists(pdf):
            os.remove(pdf)
        for p in item_barcodes:
            if os.path.exists(p):
                os.remove(p)

        # Reset cart and UI
        self.cart.clear()
        self.grand_total_var.set(0)
        self.cart_tree.delete(*self.cart_tree.get_children())
        self.update_subtotal()
        self.update_grand_total()
        self.name_var.set("")
        self.phone_var.set("")

        messagebox.showinfo("Success", f"Bill {bn} done.")
        if hasattr(self, 'last_bill_label'):
            self.last_bill_label.config(text=f"Last Bill #: {bn}")


    def show_old_data(self):
        win = tk.Toplevel(self.root)
        win.title("Old Data")
        win.geometry("1000x800")  # increased height for search bar

        # ——— Search by Bill# or Mobile ———
        search_frame = ttk.Frame(win)
        search_frame.pack(fill="x", pady=(5,0), padx=10)
        ttk.Label(search_frame, text="Search Bill No/Mobile:").pack(side="left")
        self.old_search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=self.old_search_var, width=20).pack(side="left", padx=(5,10))
        ttk.Button(search_frame, text="Search", command=lambda: render_table()).pack(side="left")

        # --- Option selectors ---
        opt_frame = ttk.Frame(win)
        opt_frame.pack(fill="x", pady=5)
        table_var = tk.StringVar(value="registerorder")

        def render_table():
            tbl = table_var.get()
            # clear existing
            for col in tree["columns"]:
                tree.heading(col, text="")
            tree.delete(*tree.get_children())

            # fetch new columns
            self.cursor.execute(f"PRAGMA table_info({tbl})")
            cols = [info[1] for info in self.cursor.fetchall()]
            tree["columns"] = cols

            # compute width per column
            total_w = 780
            col_w = max(80, total_w // max(1, len(cols)))
            for c in cols:
                tree.heading(c, text=c)
                tree.column(c, width=col_w, anchor="center")

            # apply optional filter
            search_text = self.old_search_var.get().strip()
            if search_text:
                sql = f"SELECT * FROM {tbl} WHERE barcode_no LIKE ? OR mobile_no LIKE ?"
                params = (f"%{search_text}%", f"%{search_text}%")
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(f"SELECT * FROM {tbl}")

            for row in self.cursor.fetchall():
                tree.insert("", "end", values=row)

        ttk.Radiobutton(opt_frame, text="Registered Orders", variable=table_var,
                        value="registerorder", command=render_table).pack(side="left", padx=10)
        ttk.Radiobutton(opt_frame, text="Ready Items", variable=table_var,
                        value="readyitems",    command=render_table).pack(side="left", padx=10)

        # --- Treeview with scrollbars ---
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        vsb = ttk.Scrollbar(frame, orient="vertical")
        hsb = ttk.Scrollbar(frame, orient="horizontal")
        tree = ttk.Treeview(frame, show="headings",
                            yscrollcommand=vsb.set,
                            xscrollcommand=hsb.set)
        vsb.config(command=tree.yview)
        hsb.config(command=tree.xview)

        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True)

        # initial load
        render_table()
                    
    # --- REPLACE the whole open_ready_window() definition with this version ----------
    # Updated open_ready_window to support manual 'ready' marking via bill search
# as well as barcode scan-based automatic ready marking

    def open_ready_window(self):
        """
        Scan any  <billNo>_<itemId>_<unitSeq>  barcode and mark the WHOLE item ready
        immediately (even on the very first scan that also loads the bill grid).
        Also allows manual ready marking via bill number.
        """
        import json
        from tkinter import ttk, messagebox
        import tkinter as tk

        def norm_id(raw: str) -> str:
            return str(int(raw)) if raw.isdigit() else raw

        win = tk.Toplevel(self.root)
        win.title("Ready Items (scan or manual)")
        win.attributes("-fullscreen", True)

        # ── Barcode Entry ──
        ttk.Label(win, text="Scan any *unit* barcode to mark its item Ready:", font=("Segoe UI", 11, "bold")).pack(pady=(12, 6))
        scan_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=scan_var, font=("Segoe UI", 12), width=44)
        entry.pack()
        entry.focus()

        # ── Manual Search ──
        search_frame = ttk.Frame(win); search_frame.pack(pady=10)
        ttk.Label(search_frame, text="Or enter Bill No manually:").pack(side="left", padx=(4, 5))
        search_var = tk.StringVar()
        ttk.Entry(search_frame, textvariable=search_var, width=20).pack(side="left")
        ttk.Button(search_frame, text="Search", command=lambda: manual_load(search_var.get())).pack(side="left", padx=6)

        # ── Treeview ──
        cols = ("ItemID", "Product", "Qty", "Units", "Ready?")
        frame = ttk.Frame(win); frame.pack(fill="both", expand=True, padx=10, pady=10)
        vsb = ttk.Scrollbar(frame, orient="vertical")
        tree = ttk.Treeview(frame, columns=cols, show="headings", yscrollcommand=vsb.set)
        vsb.config(command=tree.yview); vsb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        widths = {"ItemID": 70, "Product": 260, "Qty": 60, "Units": 60, "Ready?": 70}
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, anchor="center", width=widths[c])

        # ── Buttons ──
        btns = ttk.Frame(win); btns.pack(pady=(0, 12))
        ttk.Button(btns, text="Mark Selected as Ready", command=lambda: mark_selected_ready()).pack(side="left", padx=10)
        ttk.Button(btns, text="Mark All as Ready", command=lambda: mark_all_ready()).pack(side="left", padx=10)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right", padx=10)

        self._current_ready_bill = None
        cart_cache = None

        def load_bill(bill_no: str):
            tree.delete(*tree.get_children())
            self.cursor.execute("SELECT details FROM bills WHERE bill_number = ?", (bill_no,))
            row = self.cursor.fetchone()
            if not row or not row[0]:
                messagebox.showerror("Error", f"No cart data for bill {bill_no}")
                return None
            cart = json.loads(row[0])
            grouped = {}
            for it in cart:
                self.cursor.execute("SELECT id FROM itemlist WHERE item_name = ?", (it["product"],))
                idrow = self.cursor.fetchone()
                item_id = norm_id(str(idrow[0]) if idrow else it["product"])
                info = grouped.setdefault(item_id, {"name": it["product"], "qty": 0, "units": 0, "Ready": False})
                info["qty"] += int(it["qty"])
                info["units"] += int(it["units"])
                if it.get("Ready"): info["Ready"] = True
            for iid, inf in grouped.items():
                tree.insert("", "end", iid=iid, values=(iid, inf["name"], inf["qty"], inf["units"], "Yes" if inf["Ready"] else "No"))
            return cart

        def manual_load(bill_no):
            nonlocal cart_cache
            bill_no = bill_no.strip()
            if not bill_no:
                return
            self._current_ready_bill = bill_no
            cart_cache = load_bill(bill_no)

        def mark_item_ready(item_id: str):
            nonlocal cart_cache
            changed = False
            for it in cart_cache:
                self.cursor.execute("SELECT id FROM itemlist WHERE item_name = ?", (it["product"],))
                idrow = self.cursor.fetchone()
                line_id = norm_id(str(idrow[0]) if idrow else it["product"])
                if line_id == item_id and not it.get("Ready", False):
                    it["Ready"] = True
                    changed = True
            if not changed:
                return False
            self.cursor.execute("UPDATE bills SET details = ?, Ready = 1 WHERE bill_number = ?", (json.dumps(cart_cache), self._current_ready_bill))
            self.conn.commit()
            if tree.exists(item_id):
                tree.set(item_id, "Ready?", "Yes")
            return True

        def mark_selected_ready():
            sel = tree.selection()
            if not sel or not self._current_ready_bill:
                return
            for iid in sel:
                mark_item_ready(iid)

        def mark_all_ready():
            if not self._current_ready_bill:
                return
            for iid in tree.get_children():
                mark_item_ready(iid)

        def on_scan(_evt=None):
            nonlocal cart_cache
            code = scan_var.get().strip(); scan_var.set("")
            if not code: return
            try:
                bill_no, raw_item, _seq = code.split("_", 2)
            except ValueError:
                messagebox.showerror("Error", f"Bad barcode format:\n{code}")
                return
            item_id = norm_id(raw_item)
            if self._current_ready_bill is None:
                self._current_ready_bill = bill_no
                cart_cache = load_bill(bill_no)
                if cart_cache is None:
                    self._current_ready_bill = None
                    return
                mark_item_ready(item_id)
                return
            if bill_no != self._current_ready_bill:
                messagebox.showerror("Error", f"Window locked to bill {self._current_ready_bill}.\nScanned code from bill {bill_no}.")
                return
            mark_item_ready(item_id)

        entry.bind("<Return>", on_scan)


        # No initial population: user must scan first to set bill context


    def show_orders_by_mobile(self):
        pw = tk.Toplevel(self.root)
        pw.title("Search Orders by Mobile")
        pw.geometry("700x500")
        frm = ttk.Frame(pw); frm.pack(pady=10)
        ttk.Label(frm, text="Customer Mobile:").pack(side="left", padx=5)
        mv = tk.StringVar()
        ttk.Entry(frm, textvariable=mv).pack(side="left", padx=5)
        ttk.Button(frm, text="Search", command=lambda: load(mv.get().strip())).pack(side="left", padx=5)
        cols = ("Bill Number","Bill Date","Completed","Delivered Date")
        tr = ttk.Treeview(pw, columns=cols, show="headings")
        for c in cols:
            tr.heading(c,text=c); tr.column(c,anchor="center")
        tr.pack(fill="both", expand=True, pady=10)
        def load(mobile):
            for iid in tr.get_children(): tr.delete(iid)
            self.cursor.execute("""
                SELECT b.bill_number, b.bill_date,
                       CASE WHEN b.completed=1 THEN 'Yes' ELSE 'No' END,
                       COALESCE(b.delivered_date,'')
                FROM bills b
                JOIN customerentry c ON c.id=b.customer_id
                WHERE c.mobile=?
                ORDER BY b.bill_date DESC
            """, (mobile,))
            for bn,bd,comp,dd in self.cursor.fetchall():
                tr.insert("", "end", values=(bn,bd,comp,dd))

    def show_orders(self):
        """
        Opens (or raises) the All Orders window. The window is kept on top of the
        main app and never closes while you work.
        """
        import re, json, os
        from datetime import datetime
        import tkinter as tk
        from tkinter import ttk, messagebox

        if hasattr(self, "_orders_win") and self._orders_win.winfo_exists():
            self._orders_win.lift()
            return

        def extract_bill(txt: str) -> tuple[str, str] | None:
            txt = txt.strip()
            if not txt:
                return None
            if txt.isdigit():
                return ("mobile", txt)
            m = re.match(r"^(\d+)_\w+_\d+$", txt)
            if m:
                return ("bill", m.group(1))
            return ("bill", txt)

        def refresh(mobile_filter: tuple[str, str] | None = None):
            tr.delete(*tr.get_children())

            if mobile_filter:
                mode, value = mobile_filter
                if mode == "mobile":
                    self.cursor.execute("""
                        SELECT customerentry.name, bill_number, total_amount,
                            is_cash, is_gpay, is_indusind_bank,
                            details, bill_date, completed, ready
                        FROM bills
                        JOIN customerentry ON customerentry.id = bills.customer_id
                        WHERE customerentry.mobile LIKE ?
                        ORDER BY bill_date DESC
                    """, (f"%{value}%",))
                else:
                    self.cursor.execute("""
                        SELECT customerentry.name, bill_number, total_amount,
                            is_cash, is_gpay, is_indusind_bank,
                            details, bill_date, completed, ready
                        FROM bills
                        JOIN customerentry ON customerentry.id = bills.customer_id
                        WHERE bill_number = ?
                        ORDER BY bill_date DESC
                    """, (value,))
            else:
                self.cursor.execute("""
                    SELECT customerentry.name, bill_number, total_amount,
                        is_cash, is_gpay, is_indusind_bank,
                        details, bill_date, completed, ready
                    FROM bills
                    JOIN customerentry ON customerentry.id = bills.customer_id
                    ORDER BY bill_date DESC
                """)

            rows = self.cursor.fetchall()
            print("[DEBUG] Rows fetched:", len(rows))

            for (cust_name, bn, amt, c, g, i, det, bd, comp, ready_) in rows:
                mode = "Cash" if c else "GPay" if g else "IndusInd Bank" if i else ""

                try:
                    items = json.loads(det)
                    if isinstance(items[0], dict):
                        product_lines = [f"{item['product']} - {item['service']}" for item in items]
                    else:
                        product_lines = [f"{item[0]} - {item[1]}" for item in items]
                    detail_text = ", ".join(product_lines)
                except Exception:
                    detail_text = str(det)[:100]

                tr.insert("", "end", values=(
                    cust_name, bn, f"₹{amt:.2f}", mode, detail_text, bd,
                    "Yes" if comp else "No", "Yes" if ready_ else "No"
                ))


        self._orders_win = tk.Toplevel(self.root)
        op = self._orders_win
        op.title("All Orders")
        op.attributes("-fullscreen", True)
        op.transient(self.root)
        op.attributes("-topmost", True)

        top = ttk.Frame(op); top.pack(fill="x", pady=(10, 0))
        ttk.Label(top, text="Mobile Number / Scan:", font=("Segoe UI", 10)).pack(side="left", padx=(14, 6))

        sv = tk.StringVar()
        ent = ttk.Entry(top, textvariable=sv, width=26, font=("Segoe UI", 11))
        ent.pack(side="left", padx=(0, 6))
        ent.focus()

        ent.bind("<Return>", lambda e=None: refresh(extract_bill(sv.get())))
        ttk.Button(top, text="Search", command=lambda: refresh(extract_bill(sv.get()))).pack(side="left", padx=(0, 6))

        cols = ("Customer", "BillNo", "Total", "Mode", "Details", "Date", "Completed", "Ready")
        tr = ttk.Treeview(op, columns=cols, show="headings")

        style = ttk.Style()
        style.configure("Treeview", rowheight=60)

        widths = {
            "Customer": 140,
            "BillNo": 50,
            "Total": 60,
            "Mode": 60,
            "Details": 600,
            "Date": 140,
            "Completed": 40,
            "Ready": 40
        }

        for c in cols:
            tr.heading(c, text=c)
            tr.column(c, anchor="center", width=widths.get(c, 100))

        tr.pack(fill="both", expand=True, padx=10, pady=6)

        bar = ttk.Frame(op); bar.pack(pady=4)
        ttk.Button(bar, text="Mark Completed", command=lambda: mark()).grid(row=0, column=0, padx=5)
        ttk.Button(bar, text="Regenerate Bill", command=lambda: regen_bill()).grid(row=0, column=1, padx=5)
        ttk.Button(bar, text="Regenerate Barcode", command=lambda: regen_barcode()).grid(row=0, column=2, padx=5)
        ttk.Button(bar, text="Close", command=op.destroy).grid(row=0, column=3, padx=5)

        q_base = """
            SELECT id, customer_id, bill_number, total_amount,
                is_cash, is_gpay, is_indusind_bank,
                details, bill_date, completed, ready
            FROM bills
        """

        refresh()  # show all orders by default


        def mark():
            sel = tr.selection()
            if not sel:
                messagebox.showerror("Error", "Select an order")
                return

            # payment-mode popup centered
            pmw = tk.Toplevel(op)
            pmw.title("Payment Mode")
            pmw.transient(op)
            pmw.attributes("-topmost", True)

            # center the popup
            pmw.update_idletasks()
            w, h = 300, 200
            x = (pmw.winfo_screenwidth() // 2) - (w // 2)
            y = (pmw.winfo_screenheight() // 2) - (h // 2)
            pmw.geometry(f"{w}x{h}+{x}+{y}")

            pm = tk.StringVar()
            ttk.Label(pmw, text="Payment Mode:").pack(padx=12, pady=(12, 4))
            for t, v in (("Cash", "Cash"), ("Google Pay", "GooglePay"), ("IndusInd Bank", "IndusIndBank")):
                ttk.Radiobutton(pmw, text=t, variable=pm, value=v).pack(anchor="w", padx=20)
            ttk.Button(pmw, text="OK", command=pmw.destroy).pack(pady=10)

            pmw.wait_window()
            if not pm.get(): return

            is_cash, is_g, is_i = (pm.get() == "Cash"), (pm.get() == "GooglePay"), (pm.get() == "IndusIndBank")
            oid = tr.item(sel[0])["values"][0]
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.cursor.execute("""
                UPDATE bills SET completed=1, delivered_date=?,
                    is_cash=?, is_gpay=?, is_indusind_bank=? WHERE id=?""",
                (ts, is_cash, is_g, is_i, oid))
            self.conn.commit()
            refresh(extract_bill(sv.get()))    

        def regen_bill():
            sel = tr.selection()
            if not sel:
                messagebox.showerror("Error", "Select an order")
                return

            vals = tr.item(sel[0])["values"]
            oid = vals[0]
            bn = str(vals[2])
            total_txt = vals[3]

            try:
                total = float(str(total_txt).lstrip("₹"))
            except ValueError:
                messagebox.showerror("Error", f"Cannot parse total {total_txt!r}")
                return

            self.cursor.execute("SELECT cart_data, customer_id FROM bills WHERE id = ?", (oid,))
            row = self.cursor.fetchone()
            if not row or not row[0]:
                messagebox.showerror("Error", f"No cart_data for order {bn}")
                return
            cart_json, cid = row
            cart_dicts = json.loads(cart_json)

            cart_items = [
                (
                    it.get("product", ""),
                    it.get("service", ""),
                    float(it.get("price", 0)),
                    int(it.get("qty", 0)),
                    int(it.get("units", 0)),
                    float(it.get("total_amt", 0))
                )
                for it in cart_dicts
            ]

            self.cursor.execute("SELECT name, mobile FROM customerentry WHERE id = ?", (cid,))
            name, mob = self.cursor.fetchone()

            pdf_path, _ = generate_bill_pdf(
                customer_name=name,
                customer_phone=mob,
                details=cart_json,
                total_amount=total,
                bill_number=bn,
                cart_items=cart_items
            )

            self.cursor.execute(
                "UPDATE bills SET pdf_path = ? WHERE id = ?",
                (pdf_path, oid)
            )
            self.conn.commit()

            print_bill(pdf_path)
            messagebox.showinfo("Success", f"Bill {bn} regenerated.")
            refresh()

        def regen_barcode():
            sel = tr.selection()
            if not sel:
                messagebox.showerror("Error", "Select an order")
                return

            vals = tr.item(sel[0])["values"]
            oid = vals[0]
            bn = str(vals[2])

            self.cursor.execute("SELECT cart_data, customer_id FROM bills WHERE id = ?", (oid,))
            row = self.cursor.fetchone()
            if not row or not row[0]:
                messagebox.showerror("Error", f"No cart_data for order {bn}")
                return
            cart_json, cid = row
            cart_dicts = json.loads(cart_json)

            cart_items = [
                (
                    it.get("product", ""),
                    it.get("service", ""),
                    float(it.get("price", 0)),
                    int(it.get("qty", 0)),
                    int(it.get("units", 0)),
                    float(it.get("total_amt", 0))
                )
                for it in cart_dicts
            ]

            self.cursor.execute("SELECT name FROM customerentry WHERE id = ?", (cid,))
            name = self.cursor.fetchone()[0]

            import re, os
            from datetime import datetime
            piece_pattern = re.compile(r'(\d+)\s*(?:pc|pcs|piece|pieces)\b', re.IGNORECASE)
            ts = datetime.now().strftime("%H%M%S")
            barcode_files = []

            for prod, srv, price, qty, units, total_amt in cart_items:
                if srv.strip().lower() == "steam press":
                    continue

                self.cursor.execute("SELECT id FROM itemlist WHERE item_name = ?", (prod,))
                r = self.cursor.fetchone()
                item_id = str(r[0]) if r else prod.replace(" ", "_")

                m = piece_pattern.search(prod)
                pcs = int(m.group(1)) if m else 1
                total_pieces = pcs * qty

                for i in range(1, total_pieces + 1):
                    payload = f"{bn}_{item_id}_{i}_{ts}"
                    footer = f"{name} | {prod} | {srv}"
                    fname = os.path.join(base_path, f"{bn}_{item_id}_{i}_{ts}")
                    path = generate_barcode(
                        data=payload,
                        filename_prefix=fname,
                        display_text=footer,
                        target_mm_width=40,
                        dpi=203
                    )
                    barcode_files.append(path)

            print_barcodes(barcode_files)
            messagebox.showinfo("Success", f"Barcodes for bill {bn} regenerated.")
            refresh()




    def show_date_wise_orders(self):
        dp = tk.Toplevel(self.root)
        dp.title("Date Wise Orders")
        dp.geometry("900x600")

        cols = ("Date","Count","Total","CashSales","GPaySales","IndusIndSales")
        tr = ttk.Treeview(dp, columns=cols, show="headings")
        tr.heading("Date", text="Bill Date");      tr.column("Date", width=100, anchor="center")
        tr.heading("Count", text="Order Count");   tr.column("Count", width=80, anchor="center")
        tr.heading("Total", text="Total Sales");   tr.column("Total", width=100, anchor="center")
        tr.heading("CashSales", text="Cash Sales");tr.column("CashSales", width=100, anchor="center")
        tr.heading("GPaySales", text="GPay Sales");tr.column("GPaySales", width=100, anchor="center")
        tr.heading("IndusIndSales", text="IndusInd Bank Sales"); tr.column("IndusIndSales", width=140, anchor="center")
        tr.pack(fill="both", expand=True)

        self.cursor.execute("""
            SELECT
              substr(bill_date,1,10) AS dt,
              COUNT(*)                 AS cnt,
              SUM(total_amount)        AS tot,
              SUM(CASE WHEN is_cash=1          THEN total_amount ELSE 0 END) AS cash_tot,
              SUM(CASE WHEN is_gpay=1          THEN total_amount ELSE 0 END) AS gpay_tot,
              SUM(CASE WHEN is_indusind_bank=1 THEN total_amount ELSE 0 END) AS indus_tot
            FROM bills
            GROUP BY dt
            ORDER BY dt DESC
        """)
        for dt, cnt, tot, cash_tot, gpay_tot, indus_tot in self.cursor.fetchall():
            tr.insert("", "end", values=(
                dt,
                cnt,
                f"₹{tot:.2f}",
                f"₹{cash_tot:.2f}",
                f"₹{gpay_tot:.2f}",
                f"₹{indus_tot:.2f}"
            ))
    
    def show_daily_register(self):
        import json
        import tempfile
        import webbrowser
        from datetime import datetime
        import tkinter as tk
        from tkinter import ttk
        from tkcalendar import DateEntry

        # ─── Window setup ────────────────────────────────────────────────────────
        win = tk.Toplevel(self.root)
        win.title("Daily Register")
        win.geometry("950x700")

        # ─── SQL ─────────────────────────────────────────────────────────────────
        query = """
            SELECT
                b.bill_number,
                b.bill_date,
                b.completed,
                c.name,
                c.mobile,
                b.details
            FROM bills AS b
            JOIN customerentry AS c
            ON c.id = b.customer_id
            WHERE substr(b.bill_date,1,10) = ?
            ORDER BY b.bill_date
        """

        # ─── Top controls ─────────────────────────────────────────────────────────
        top_frame = ttk.Frame(win)
        top_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(top_frame, text="Select Date:").pack(side="left")
        date_var = tk.StringVar()
        date_entry = DateEntry(
            top_frame,
            textvariable=date_var,
            date_pattern="yyyy-MM-dd",
            width=12
        )
        date_entry.set_date(datetime.now())
        date_entry.pack(side="left", padx=(5, 10))

        show_btn = ttk.Button(
            top_frame,
            text="Show",
            command=lambda: load_data(date_var.get())
        )
        show_btn.pack(side="left")

        print_btn = ttk.Button(
            top_frame,
            text="Print",
            command=lambda: export_and_print(date_var.get())
        )
        print_btn.pack(side="left", padx=(10, 0))

        # ─── Placeholder for the Treeview ─────────────────────────────────────────
        tree = None

        # ─── Load into Treeview (sorted by Item) ──────────────────────────────────
        def load_data(selected_date):
            nonlocal tree
            if tree is not None:
                tree.destroy()

            # New column order: Qty, Units, BillNo, Item, Time, Completed, Customer, Mobile
            cols = ("Qty", "Units", "BillNo", "Item", "Time", "Completed", "Customer", "Mobile")
            widths = {
                "Qty": 30,
                "Units": 30,
                "BillNo": 40,
                "Item": 400,
                "Time": 100,
                "Completed": 60,
                "Customer": 150,
                "Mobile": 120
            }

            tree = ttk.Treeview(win, columns=cols, show="headings")
            for col in cols:
                tree.heading(col, text=col)
                tree.column(col, anchor="center", width=widths[col])
            tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            # collect all rows, then sort by Item
            rows = []
            self.cursor.execute(query, (selected_date,))
            for bn, bd, comp, customer, mobile, details_json in self.cursor.fetchall():
                dt_obj     = datetime.strptime(str(bd), "%Y-%m-%d %H:%M:%S")
                time_only  = dt_obj.strftime("%H:%M:%S")
                comp_status= "Yes" if comp else "No"

                try:
                    items = json.loads(details_json)
                except Exception:
                    items = []

                for it in items:
                    if isinstance(it, dict):
                        prod  = it.get("product", "")
                        srv   = it.get("service", "")
                        qty   = int(it.get("qty", 0))
                        units = int(it.get("units", 0))
                    else:
                        prod  = it[0] if len(it) > 0 else ""
                        srv   = it[1] if len(it) > 1 else ""
                        qty   = int(it[3]) if len(it) > 3 else 0
                        units = int(it[4]) if len(it) > 4 else 0

                    item_text = f"{prod}({srv})"
                    rows.append((
                        qty,
                        units,
                        bn,
                        item_text,
                        time_only,
                        comp_status,
                        customer or "",
                        mobile or ""
                    ))

            # sort by Item (index 3)
            rows.sort(key=lambda r: r[3].lower())

            for qty, units, bn, item, time_only, comp_status, customer, mobile in rows:
                tree.insert("", "end", values=(
                    qty, units, bn, item, time_only, comp_status, customer, mobile
                ))

        # ─── Export & Print (sorted by Item, omit Date) ────────────────────────────
        def export_and_print(selected_date):
            entries = []
            self.cursor.execute(query, (selected_date,))
            for bn, bd, comp, customer, mobile, details_json in self.cursor.fetchall():
                dt_obj     = datetime.strptime(str(bd), "%Y-%m-%d %H:%M:%S")
                time_only  = dt_obj.strftime("%H:%M:%S")
                comp_status= "Yes" if comp else "No"

                try:
                    items = json.loads(details_json)
                except Exception:
                    items = []

                for it in items:
                    if isinstance(it, dict):
                        prod  = it.get("product", "")
                        srv   = it.get("service", "")
                        qty   = int(it.get("qty", 0))
                        units = int(it.get("units", 0))
                    else:
                        prod  = it[0] if len(it) > 0 else ""
                        srv   = it[1] if len(it) > 1 else ""
                        qty   = int(it[3]) if len(it) > 3 else 0
                        units = int(it[4]) if len(it) > 4 else 0

                    item_text = f"{prod}({srv})"
                    row_html = (
                        "<tr>"
                        f"<td>{qty}</td>"
                        f"<td>{units}</td>"
                        f"<td>{bn}</td>"
                        f"<td>{item_text}</td>"
                        f"<td>{time_only}</td>"
                        f"<td>{comp_status}</td>"
                        f"<td>{customer or ''}</td>"
                        f"<td>{mobile or ''}</td>"
                        "</tr>"
                    )
                    entries.append((item_text.lower(), row_html))

            # sort by item_text
            entries.sort(key=lambda x: x[0])
            rows_html = "\n".join(html for _, html in entries)

            headers = (
                "<th>Qty</th>"
                "<th>Units</th>"
                "<th>BillNo</th>"
                "<th>Item</th>"
                "<th>Time</th>"
                "<th>Completed</th>"
                "<th>Customer</th>"
                "<th>Mobile</th>"
            )

            html = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Daily Register – {selected_date}</title>
    <style>
    @page {{ size: A4; margin: 1cm; }}
    body {{ font-family: sans-serif; font-size: 10px; }}
    table {{
        width: 100%;
        border-collapse: collapse;
        table-layout: auto;
    }}
    th, td {{
        border: 1px solid #000;
        padding: 4px;
        text-align: center;
        white-space: nowrap;
    }}
    /* shrink Qty (1st) & Units (2nd) */
    th:nth-child(1), td:nth-child(1),
    th:nth-child(2), td:nth-child(2) {{
        width: 1%;
    }}
    th {{ background: #eee; }}
    </style>
    </head>
    <body onload="window.print()">
    <h2>Daily Register for {selected_date}</h2>
    <table>
        <tr>{headers}</tr>
        {rows_html}
    </table>
    </body>
    </html>"""

            tmp = tempfile.NamedTemporaryFile('w', delete=False, suffix='.html', encoding='utf-8')
            tmp.write(html)
            tmp.close()
            webbrowser.open(f"file://{tmp.name}", new=2)

        # ─── Initial load ─────────────────────────────────────────────────────────
        load_data(datetime.now().strftime("%Y-%m-%d"))

if __name__ == "__main__":
    initialize_db()
    threading.Thread(target=start_node_server, daemon=True).start()
    time.sleep(2)
    root = tk.Tk()
    set_scaling(root, 2.0)
    app = BillingApp(root)
    root.mainloop()
