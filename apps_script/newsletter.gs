/**
 * BioMed AI Watch newsletter: subscriptions and the weekly send.
 *
 * Source of truth: github.com/DKundnani/biomedi-ai-watch (apps_script/).
 * It is pasted into the same Apps Script project as the website's mail relay
 * (dkundnani.github.io/scripts/mail-relay.gs), so sign-ups pass that relay's
 * spam gate (honeypot, page stamp, captcha, hourly cap) before reaching
 * subscribe(). The relay calls two functions defined here:
 *   subscribe(data)        from doPost when data._action === "subscribe"
 *   newsletterLink(params) from doGet when ?action=confirm|unsubscribe
 * Subscribers are kept in a Google Sheet in Drive; sendWeekly() reads the
 * issue this repo's pipeline publishes to dkundnani.bio/newsletter/.
 *
 * One-time setup: run newsletterSetup() from the editor, then publish a new
 * version of the existing web app deployment so the URL stays the same.
 */

var NL_NAME      = "BioMed AI Watch";
var NL_FEED      = "https://dkundnani.bio/newsletter/";      // latest.json + latest.html
var NL_HEADERS   = ["email", "status", "token", "subscribed_at", "confirmed_at", "unsubscribed_at", "page", "last_sent"];

/* ----------------------------------------------------------------- setup */

function newsletterSetup() {
  var props = PropertiesService.getScriptProperties();
  var folderId = props.getProperty("NL_FOLDER_ID");
  if (!folderId) {
    var folder = DriveApp.createFolder(NL_NAME);
    folder.createFolder("Archive");
    folderId = folder.getId();
    props.setProperty("NL_FOLDER_ID", folderId);
  }
  if (!props.getProperty("NL_SHEET_ID")) {
    var ss = SpreadsheetApp.create(NL_NAME + " subscribers");
    var sh = ss.getSheets()[0];
    sh.setName("subscribers");
    sh.appendRow(NL_HEADERS);
    sh.setFrozenRows(1);
    DriveApp.getFileById(ss.getId()).moveTo(DriveApp.getFolderById(folderId));
    props.setProperty("NL_SHEET_ID", ss.getId());
  }
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === "sendWeekly") ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger("sendWeekly").timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(8).create();
  Logger.log("Subscribers sheet: " + SpreadsheetApp.openById(props.getProperty("NL_SHEET_ID")).getUrl());
}

/* ------------------------------------------------------- subscriber sheet */

function nlSheet() {
  var id = PropertiesService.getScriptProperties().getProperty("NL_SHEET_ID");
  return SpreadsheetApp.openById(id).getSheetByName("subscribers");
}

function nlRows() {
  var values = nlSheet().getDataRange().getValues();
  return values.slice(1).map(function (r, i) {
    var row = { row: i + 2 };
    NL_HEADERS.forEach(function (h, j) { row[h] = r[j]; });
    return row;
  });
}

function nlSet(row, field, value) {
  nlSheet().getRange(row, NL_HEADERS.indexOf(field) + 1).setValue(value);
}

/* --------------------------------------------------------- subscriptions */

/* Called by doPost once the spam gate has passed. Double opt-in: nobody is
   mailed an issue until they click the link sent to their own inbox. */
function subscribe(data) {
  var email = String(data.email || "").trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || email.length > 254) {
    return { ok: false, error: "Please enter a valid email address." };
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var existing = nlRows().filter(function (r) { return r.email === email; })[0];
    if (existing && existing.status === "active") return { ok: true };   // say nothing new
    var token = existing ? existing.token : Utilities.getUuid();
    if (existing) {
      nlSet(existing.row, "status", "pending");
      nlSet(existing.row, "subscribed_at", new Date());
    } else {
      nlSheet().appendRow([email, "pending", token, new Date(), "", "", String(data._page || "").substring(0, 200), ""]);
    }
    var url = nlLink("confirm", token);
    MailApp.sendEmail(email, "Confirm your subscription to " + NL_NAME,
      "Confirm your subscription: " + url + "\n\nIf you did not ask for this, ignore this email.", {
        name: NL_NAME,
        htmlBody:
          '<p>Please confirm your subscription to <b>' + NL_NAME + '</b>, a weekly briefing on AI in medicine from Deepali Kundnani.</p>' +
          '<p><a href="' + url + '" style="background:#cf4310;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Confirm subscription</a></p>' +
          '<p style="color:#666;font-size:12px">If you did not ask for this, ignore this email and you will not be subscribed.</p>'
      });
  } finally {
    lock.releaseLock();
  }
  return { ok: true };
}

function nlLink(action, token) {
  return ScriptApp.getService().getUrl() + "?action=" + action + "&token=" + encodeURIComponent(token);
}

function newsletterLink(p) {
  var r = p.token && nlRows().filter(function (x) { return x.token === p.token; })[0];
  if (!r) return nlPage("Link not recognised", "This link is invalid or has expired.");
  if (p.action === "confirm") {
    nlSet(r.row, "status", "active");
    nlSet(r.row, "confirmed_at", new Date());
    return nlPage("You're subscribed", NL_NAME + " will arrive in your inbox every Monday.");
  }
  if (p.action === "unsubscribe") {
    nlSet(r.row, "status", "unsubscribed");
    nlSet(r.row, "unsubscribed_at", new Date());
    return nlPage("Unsubscribed", "You will not receive " + NL_NAME + " again. You can resubscribe any time at dkundnani.bio/newsletter.html.");
  }
  return nlPage("Unknown link", "");
}

function nlPage(title, msg) {
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  return HtmlService.createHtmlOutput(
    '<div style="font-family:Inter,system-ui,sans-serif;max-width:520px;margin:60px auto;padding:0 16px">' +
    '<h2>' + esc(title) + '</h2><p>' + esc(msg) + '</p>' +
    '<p><a href="https://dkundnani.bio/newsletter.html" style="color:#cf4310">Back to dkundnani.bio</a></p></div>'
  ).setTitle(title);
}

/* ------------------------------------------------------------ weekly send */

function nlLatest() {
  var meta = JSON.parse(UrlFetchApp.fetch(NL_FEED + "latest.json", { headers: { "Cache-Control": "no-cache" } }).getContentText());
  var html = UrlFetchApp.fetch(NL_FEED + "latest.html", { headers: { "Cache-Control": "no-cache" } }).getContentText();
  return { meta: meta, html: html };
}

/* Runs from the Monday trigger. Safe to run again: each subscriber gets a
   given issue once, and anyone left over by the daily quota is sent next run. */
function sendWeekly() {
  var latest = nlLatest(), meta = latest.meta;
  var subs = nlRows().filter(function (r) { return r.status === "active" && String(r.last_sent) !== meta.date; });
  var quota = MailApp.getRemainingDailyQuota() - 5;            // leave room for contact-form mail
  subs.slice(0, Math.max(quota, 0)).forEach(function (r) {
    var unsub = nlLink("unsubscribe", r.token);
    MailApp.sendEmail(r.email, meta.subject, "This week's issue: " + meta.url + "\n\nUnsubscribe: " + unsub, {
      name: NL_NAME,
      htmlBody: latest.html.split("{{UNSUBSCRIBE_URL}}").join(unsub)
    });
    nlSet(r.row, "last_sent", "'" + meta.date);                // quoted so Sheets keeps it as text
  });
  if (subs.length > quota) Logger.log("Quota reached; " + (subs.length - quota) + " left for the next run.");

  var folderId = PropertiesService.getScriptProperties().getProperty("NL_FOLDER_ID");
  var archive = DriveApp.getFolderById(folderId).getFoldersByName("Archive").next();
  if (!archive.getFilesByName(meta.date + ".html").hasNext()) archive.createFile(meta.date + ".html", latest.html, MimeType.HTML);
}

/* Sends the latest issue to the script owner only. */
function sendTestToMe() {
  var latest = nlLatest();
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), "[TEST] " + latest.meta.subject, latest.meta.url, {
    name: NL_NAME, htmlBody: latest.html.split("{{UNSUBSCRIBE_URL}}").join("#test")
  });
}
