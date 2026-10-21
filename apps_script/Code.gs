/**
 * BioMed AI Watch — subscriptions and weekly sending, on your own Google account.
 *
 *   Website form --POST--> doPost   -> Google Sheet (Drive) + confirmation email (double opt-in)
 *   Confirm / unsubscribe links ---> doGet
 *   Weekly time trigger ----------> sendWeekly: fetch latest issue from GitHub, send via Gmail,
 *                                   archive a copy in Drive
 *
 * One-time setup: paste into a new Apps Script project, run setup(), then Deploy > Web app
 * (Execute as: Me, Who has access: Anyone). Put the /exec URL in WEB_APP_URL below and in the
 * website form.
 */

const CONFIG = {
  NAME: 'BioMed AI Watch',
  SITE_URL: 'https://dkundnani.bio',
  // Raw files written each week by the GitHub Action in the biomed-ai-watch repo.
  FEED_BASE: 'https://raw.githubusercontent.com/DKundnani/biomed-ai-watch/main/docs/',
  WEB_APP_URL: 'PASTE_YOUR_WEB_APP_EXEC_URL_HERE',
  SEND_DAY: ScriptApp.WeekDay.MONDAY,
  SEND_HOUR: 8, // in the script's time zone (File > Project settings)
};

const HEADERS = ['email', 'status', 'token', 'subscribed_at', 'confirmed_at', 'unsubscribed_at', 'source', 'last_sent'];
const props = PropertiesService.getScriptProperties();

// ---------- setup ----------

function setup() {
  let folderId = props.getProperty('FOLDER_ID');
  if (!folderId) {
    const folder = DriveApp.createFolder(CONFIG.NAME);
    folder.createFolder('Archive');
    folderId = folder.getId();
    props.setProperty('FOLDER_ID', folderId);
  }
  if (!props.getProperty('SHEET_ID')) {
    const ss = SpreadsheetApp.create(`${CONFIG.NAME} — Subscribers`);
    const sh = ss.getSheets()[0];
    sh.setName('subscribers');
    sh.appendRow(HEADERS);
    sh.setFrozenRows(1);
    DriveApp.getFileById(ss.getId()).moveTo(DriveApp.getFolderById(folderId));
    props.setProperty('SHEET_ID', ss.getId());
  }
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'sendWeekly')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sendWeekly').timeBased()
    .onWeekDay(CONFIG.SEND_DAY).atHour(CONFIG.SEND_HOUR).create();
  Logger.log('Sheet: %s', SpreadsheetApp.openById(props.getProperty('SHEET_ID')).getUrl());
}

// ---------- subscriber store ----------

function sheet_() {
  return SpreadsheetApp.openById(props.getProperty('SHEET_ID')).getSheetByName('subscribers');
}

function rows_() {
  const values = sheet_().getDataRange().getValues();
  return values.slice(1).map((r, i) => ({ row: i + 2, ...Object.fromEntries(HEADERS.map((h, j) => [h, r[j]])) }));
}

function set_(row, field, value) {
  sheet_().getRange(row, HEADERS.indexOf(field) + 1).setValue(value);
}

// ---------- web endpoints ----------

function doPost(e) {
  const p = (e && e.parameter) || {};
  if (p.website) return json_({ ok: true }); // honeypot field: bots fill it, people don't
  const email = String(p.email || '').trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) {
    return json_({ ok: false, error: 'Please enter a valid email address.' });
  }

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const existing = rows_().find(r => r.email === email);
    if (existing && existing.status === 'active') return json_({ ok: true, message: "You're already subscribed." });
    let token = existing ? existing.token : Utilities.getUuid();
    if (existing) {
      set_(existing.row, 'status', 'pending');
      set_(existing.row, 'subscribed_at', new Date());
    } else {
      sheet_().appendRow([email, 'pending', token, new Date(), '', '', String(p.source || 'website').slice(0, 100), '']);
    }
    sendConfirmation_(email, token);
  } finally {
    lock.releaseLock();
  }
  return json_({ ok: true, message: 'Almost done: check your inbox to confirm your subscription.' });
}

function doGet(e) {
  const p = (e && e.parameter) || {};
  const r = p.token && rows_().find(x => x.token === p.token);
  if (!r) return page_('Link not recognised', 'This link is invalid or has expired.');
  if (p.action === 'confirm') {
    set_(r.row, 'status', 'active');
    set_(r.row, 'confirmed_at', new Date());
    return page_("You're subscribed", `Thanks! ${CONFIG.NAME} will arrive in your inbox every week.`);
  }
  if (p.action === 'unsubscribe') {
    set_(r.row, 'status', 'unsubscribed');
    set_(r.row, 'unsubscribed_at', new Date());
    return page_('Unsubscribed', `You won't receive ${CONFIG.NAME} anymore. You can resubscribe any time at ${CONFIG.SITE_URL}.`);
  }
  return page_('Unknown action', '');
}

function link_(action, token) {
  return `${CONFIG.WEB_APP_URL}?action=${action}&token=${encodeURIComponent(token)}`;
}

function sendConfirmation_(email, token) {
  const url = link_('confirm', token);
  GmailApp.sendEmail(email, `Confirm your subscription to ${CONFIG.NAME}`,
    `Confirm your subscription: ${url}\n\nIf you didn't request this, ignore this email.`, {
      name: CONFIG.NAME,
      htmlBody: `<p>Please confirm your subscription to <b>${CONFIG.NAME}</b>, a weekly briefing on AI in medicine.</p>
        <p><a href="${url}" style="background:#0b5c6b;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">Confirm subscription</a></p>
        <p style="color:#666;font-size:12px">If you didn't request this, ignore this email and you won't be subscribed.</p>`,
    });
}

// ---------- weekly send ----------

function fetchLatest_() {
  const meta = JSON.parse(UrlFetchApp.fetch(CONFIG.FEED_BASE + 'latest.json').getContentText());
  const html = UrlFetchApp.fetch(CONFIG.FEED_BASE + 'latest.html').getContentText();
  return { meta, html };
}

function sendWeekly() {
  const { meta, html } = fetchLatest_();
  if (props.getProperty('LAST_SENT_DATE') === meta.date) {
    Logger.log('Issue %s already sent; skipping.', meta.date);
    return;
  }
  const subs = rows_().filter(r => r.status === 'active' && r.last_sent !== meta.date);
  const quota = MailApp.getRemainingDailyQuota();
  if (subs.length > quota) {
    Logger.log('Only %s sends left today for %s subscribers; sending what fits, rerun tomorrow.', quota, subs.length);
  }
  subs.slice(0, quota).forEach(r => {
    GmailApp.sendEmail(r.email, meta.subject, `This week's issue: ${meta.url}\n\nUnsubscribe: ${link_('unsubscribe', r.token)}`, {
      name: CONFIG.NAME,
      htmlBody: html.split('{{UNSUBSCRIBE_URL}}').join(link_('unsubscribe', r.token)),
    });
    set_(r.row, 'last_sent', "'" + meta.date); // quote so Sheets keeps it as text
  });
  if (subs.length <= quota) props.setProperty('LAST_SENT_DATE', meta.date);

  const archive = DriveApp.getFolderById(props.getProperty('FOLDER_ID')).getFoldersByName('Archive').next();
  if (!archive.getFilesByName(`${meta.date}.html`).hasNext()) {
    archive.createFile(`${meta.date}.html`, html, MimeType.HTML);
  }
}

/** Sends the latest issue only to you, the script owner. Safe to run any time. */
function sendTestToMe() {
  const me = Session.getEffectiveUser().getEmail();
  const { meta, html } = fetchLatest_();
  GmailApp.sendEmail(me, `[TEST] ${meta.subject}`, meta.url, {
    name: CONFIG.NAME, htmlBody: html.split('{{UNSUBSCRIBE_URL}}').join('#test'),
  });
  Logger.log('Sent test to %s', me);
}

// ---------- helpers ----------

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function page_(title, msg) {
  const safe = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  return HtmlService.createHtmlOutput(
    `<div style="font-family:system-ui,sans-serif;max-width:520px;margin:60px auto;padding:0 16px">
       <h2>${safe(title)}</h2><p>${safe(msg)}</p><p><a href="${CONFIG.SITE_URL}">Back to ${safe(CONFIG.SITE_URL)}</a></p></div>`
  ).setTitle(title);
}
