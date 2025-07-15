# Laundry Billing and Barcode Tagging System

A complete desktop-based billing solution for laundry shops, featuring barcode-based item tracking, PDF bill generation, WhatsApp integration, and daily register reports.

## Features

- Bill generation with item-wise and service-wise breakdown
- Auto-generated barcodes for each individual item
- PDF bill creation and printing barcodes and bills (using Ghostscript)
- Send bills to customers on WhatsApp
- Track ready items using barcode scans
- Mark orders as completed with payment mode
- Powerful order management with search and filters
- Daily sales register and reports
- Supports multiple payment types (Cash, GPay, Other Banks)
- Editable product and service database with pricing

## 🖥️ Requirements

- Windows OS (with Ghostscript & printer drivers)
- Python 3.10+ (64-bit)
- Node.js (for WhatsApp API)
- Ghostscript (install from [https://www.ghostscript.com/](https://www.ghostscript.com/))
- TSC TE244 barcode printer (or any printer just change the name as per printer name in the code)

### Python Dependencies

Install requirements.txt for all installing all the python dependencies.

### Node.js WhatsApp Server

This project expects a Node.js server running locally at `http://localhost:3000/send-message`.

## 🧾 How to Run

1. Ensure your barcode and bill printers are connected and configured in Windows.
2. Run the Node.js server (`server.js`) in the background.
3. Run the app:

```bash
python main.py
```

> The app launches in fullscreen mode with login (`Username: 0024, Password: 0024`).

## 🖨️ Printing

- Bills are printed using Ghostscript.
- Barcodes are printed using Windows API (Win32) with dynamic spacing and feed control.

## 📤 WhatsApp Integration

- Sends bills to the customer's WhatsApp using the local server.
- Uses a REST API at `http://localhost:3000/send-message` with POST payload containing:
  - `phone`, `message`, and `pdfPath`

## 🔐 Login

- Default credentials:
  - Username: `0024`
  - Password: `0024`

## 📌 Customization

You can modify:
- Printer names in `main.py` → `BILL_PRINTER`, `BARCODE_PRINTER`
- Bill footer or header in `print_bill()`
- Barcode label layout in `print_barcode()`

## 📦 Packaging

Use `pyinstaller` for creating `.exe`:

## 👩‍💻 Author

Developed by Dipanshu Bharatia, Harshiv Patel  
For commercial laundry shops in India.

If need some custom changes according to your need kindly contact at dbharatia09@gmail.com or harshivp333@gmail.com
