// server.js

const qrcode = require('qrcode');
const fs = require('fs');
const path = require('path');
const { Client, MessageMedia, LocalAuth } = require('whatsapp-web.js');
const express = require('express');
const bodyParser = require('body-parser');
const app = express();
app.use(bodyParser.json());

// ————— Serve your generated bills —————
app.use(
  '/bills',
  express.static(path.join(__dirname, 'bills'), {
    extensions: ['pdf']
  })
);
// ———————————————————————————————————————

// Ensure a “whatsapp_session” folder next to server.js
const sessionFolder = path.join(process.env.APPDATA || os.homedir(), "CrystalBilling", "whatsapp_session");
if (!fs.existsSync(sessionFolder)) {
  fs.mkdirSync(sessionFolder, { recursive: true });
}

// Initialize WhatsApp client; force dataPath = sessionFolder
const puppeteer = require('puppeteer'); // top of file

const client = new Client({
  authStrategy: new LocalAuth({
    clientId: 'server-one',
    dataPath: sessionFolder
  }),
  puppeteer: {
    executablePath: puppeteer.executablePath(), // ✅ fix
    headless: false,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    waitUntil: 'networkidle2'
  }
});

let qrCodeUrl = ''; // will hold the generated QR code (as a data URL)

client.on('qr', (qr) => {
  qrcode.toDataURL(qr, (err, url) => {
    if (err) {
      console.error('Failed to generate QR code:', err);
    } else {
      qrCodeUrl = url;
      console.log('QR code generated. Visit /login to scan.');
    }
  });
});

client.on('ready', () => {
  console.log('WhatsApp is ready! (no QR needed as long as sessionFolder exists)');
});

client.on('authenticated', () => {
  console.log('WhatsApp is authenticated and session saved to whatsapp_session/');
});

client.on('auth_failure', () => {
  console.error('Authentication failure. You’ll need to scan QR again.');
});

client.on('disconnected', async (reason) => {
  console.error(`WhatsApp disconnected: ${reason}`);
  console.log('Reinitializing in 5 seconds…');
  setTimeout(() => client.initialize(), 5000);
});

async function sendMessage(phone, message, pdfPath) {
  if (!client?.info?.wid) {
    console.error('Client not ready. Retrying in 3 seconds…');
    setTimeout(() => sendMessage(phone, message, pdfPath), 3000);
    return;
  }

  // Ensure Indian country code
  if (!phone.startsWith('91')) phone = `91${phone}`;
  if (![12, 14].includes(phone.length)) {
    throw new Error('Phone number must be 12 or 14 digits (incl. country code).');
  }

  try {
    await new Promise(res => setTimeout(res, 2000)); // small delay

    // Send text
    await client.sendMessage(`${phone}@c.us`, message);
    console.log('Message sent');

    // Send PDF if given
    if (pdfPath) {
      const media = MessageMedia.fromFilePath(pdfPath);
      await client.sendMessage(`${phone}@c.us`, media);
      console.log('PDF sent');
    }
  } catch (err) {
    if (err.message.includes('Execution context was destroyed')) {
      console.error('Context destroyed; retry in 3 seconds…');
      setTimeout(() => sendMessage(phone, message, pdfPath), 3000);
    } else {
      console.error('sendMessage error:', err);
    }
  }
}

client.initialize();

// ———— GET /login ————
// If you already have a valid session, you’ll never see a QR here.
// If no session exists (or you previously called /logout), QR is shown.
app.get('/login', (req, res) => {
  // If client is already authenticated, just tell the user:
  if (client.info?.wid) {
    return res.send(`
      <h3>Already logged in. No QR needed.</h3>
      <p>If you truly want to log in again, first POST to <code>/logout</code>.</p>
    `);
  }

  // Otherwise, show the QR code data URL
  if (!qrCodeUrl) {
    return res.status(400).send('QR code not generated yet. Please wait a moment.');
  }

  res.send(`
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>WhatsApp Login</title>
      </head>
      <body>
        <h1>Scan this QR code in WhatsApp</h1>
        <img src="${qrCodeUrl}" alt="QR Code" />
        <p>After scanning, this page will become obsolete.</p>
      </body>
    </html>
  `);
});

// ———— POST /send-message ————
app.post('/send-message', async (req, res) => {
  const { phone, message, pdfPath } = req.body;

  try {
    await sendMessage(phone, message, pdfPath);
    res.status(200).send('Message sent successfully!');
  } catch (err) {
    console.error('Error in /send-message:', err);
    res.status(500).send('Failed to send message.');
  }
});

// ———— POST /logout ————
// Explicitly log out and clear whatsapp_session so that next time you must scan QR.
app.post('/logout', async (req, res) => {
  try {
    await client.logout();
    // Remove all files under whatsapp_session:
    fs.rmSync(sessionFolder, { recursive: true, force: true });
    // Re‐create an empty folder so LocalAuth can reinitialize later:
    fs.mkdirSync(sessionFolder, { recursive: true });
    qrCodeUrl = ''; // clear any previous QR

    console.log('Client logged out, sessionFolder cleared.');
    res.send('Logged out successfully. Next time /login will show a QR.');
  } catch (err) {
    console.error('Error during logout:', err);
    res.status(500).send('Logout failed.');
  }
});

app.listen(3000, () => {
  console.log('WhatsApp server listening on port 3000');
  console.log('Visit http://localhost:3000/login to scan (if needed)');
});

module.exports = { sendMessage };
