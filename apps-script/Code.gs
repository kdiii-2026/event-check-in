// Paste this into Extensions > Apps Script inside your Google Sheet.
// Replace SECRET below with the exact value of "webapp_secret" in server/config.json.

var SECRET = "PASTE_YOUR_SECRET_HERE";

function doGet(e) {
  var secret = e.parameter.secret;
  if (secret !== SECRET) {
    return json_({ ok: false, error: "bad secret" });
  }
  if (e.parameter.action === "get_data") {
    return json_({ ok: true, sheets: getAllSheetsData_() });
  }
  return json_({ ok: true, message: "Event check-in webhook is live" });
}

function getAllSheetsData_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var out = {};
  ss.getSheets().forEach(function (sheet) {
    out[sheet.getName()] = sheet.getDataRange().getValues();
  });
  return out;
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return json_({ ok: false, error: "bad JSON body" });
  }

  if (body.secret !== SECRET) {
    return json_({ ok: false, error: "bad secret" });
  }

  try {
    if (body.action === "full_sync") {
      fullSync_(body.events);
    } else if (body.action === "update_one") {
      updateOne_(body.label, body.row, body.col, body.values);
    } else {
      return json_({ ok: false, error: "unknown action: " + body.action });
    }
    return json_({ ok: true });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function fullSync_(events) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  events.forEach(function (ev) {
    var sheet = ss.getSheetByName(ev.label);
    if (!sheet) sheet = ss.insertSheet(ev.label);
    sheet.clearContents();
    if (ev.rows.length) {
      sheet.getRange(1, 1, ev.rows.length, ev.rows[0].length).setValues(ev.rows);
      sheet.setFrozenRows(1);
    }
  });
}

function updateOne_(label, row, col, values) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(label);
  if (!sheet) throw new Error("no tab named " + label + " -- run a full sync first");
  sheet.getRange(row, col, 1, values.length).setValues([values]);
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
