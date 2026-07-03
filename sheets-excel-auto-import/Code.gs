/**
 * 엑셀(거래내역) 파일을 업로드하면 지정된 구글 시트에 자동으로 옮겨 적는 스크립트.
 *
 * 대상 스프레드시트: https://docs.google.com/spreadsheets/d/17m7yXKC8Pow9ovak5j_5_74sNckMH2bldRR0C-lG78M
 * 대상 탭(gid): 964659478
 *
 * 매핑 규칙
 *  - 엑셀 '일시'      -> 시트 '결제일'   (없으면 '주문일시')
 *  - 엑셀 '금액'      -> 시트 '결제금액' (없으면 '주문금액')
 *  - 엑셀 '계좌적요'  -> 시트 '구매자'   (없으면 '회원명')
 *
 * 규칙
 *  - 금액이 음수(환불/이체)인 행은 제외
 *  - '일시' 기준 오름차순 정렬 후 기재
 *  - A~W열이 전부 비어있는 첫 행부터 순서대로 기재 (그 위에 이미 있는 값은 건드리지 않음)
 */

const SPREADSHEET_ID = '17m7yXKC8Pow9ovak5j_5_74sNckMH2bldRR0C-lG78M';
const TARGET_SHEET_GID = 964659478;
const LAST_COL = 23; // A ~ W
const HEADER_ROW = 1;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('엑셀 자동입력')
    .addItem('엑셀 파일 업로드', 'showUploadDialog')
    .addToUi();
}

function showUploadDialog() {
  const html = HtmlService.createHtmlOutputFromFile('UploadDialog')
    .setWidth(420)
    .setHeight(280);
  SpreadsheetApp.getUi().showModalDialog(html, '엑셀 파일 업로드');
}

function getTargetSheet_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheets = ss.getSheets();
  for (const sh of sheets) {
    if (sh.getSheetId() === TARGET_SHEET_GID) return sh;
  }
  throw new Error('대상 시트를 찾을 수 없습니다 (gid: ' + TARGET_SHEET_GID + ')');
}

function findHeaderColumns_(sheet) {
  const headerValues = sheet.getRange(HEADER_ROW, 1, 1, LAST_COL).getValues()[0];
  const result = {};
  headerValues.forEach(function (h, idx) {
    const name = String(h).trim();
    if (name) result[name] = idx + 1; // 1-based column index
  });
  return result;
}

function findFirstBlankRow_(sheet) {
  const lastRow = Math.max(sheet.getLastRow(), HEADER_ROW);
  const scanRows = lastRow - HEADER_ROW + 1;
  if (scanRows <= 0) return HEADER_ROW + 1;

  const values = sheet.getRange(HEADER_ROW + 1, 1, scanRows, LAST_COL).getValues();
  for (let i = 0; i < values.length; i++) {
    const isBlank = values[i].every(function (cell) {
      return cell === '' || cell === null;
    });
    if (isBlank) return HEADER_ROW + 1 + i;
  }
  return lastRow + 1;
}

/**
 * 클라이언트(UploadDialog.html)에서 파싱한 레코드를 받아 시트에 기재한다.
 * records: [{ dateStr, amount, payer }]
 * return: 실제로 기재된 행 수
 */
function importRecords(records) {
  const sheet = getTargetSheet_();
  const headerCols = findHeaderColumns_(sheet);

  const dateCol = headerCols['결제일'] || headerCols['주문일시'];
  const amountCol = headerCols['결제금액'] || headerCols['주문금액'];
  const payerCol = headerCols['구매자'] || headerCols['회원명'];

  if (!dateCol || !amountCol || !payerCol) {
    throw new Error('대상 시트에서 결제일/결제금액/구매자(또는 주문일시/주문금액/회원명) 열을 찾을 수 없습니다.');
  }

  const parsed = records
    .map(function (r) {
      return {
        date: new Date(r.dateStr),
        amount: Number(r.amount),
        payer: r.payer
      };
    })
    .filter(function (r) {
      return r.amount > 0 && !isNaN(r.date.getTime());
    })
    .sort(function (a, b) {
      return a.date - b.date;
    });

  const startRow = findFirstBlankRow_(sheet);

  parsed.forEach(function (r, i) {
    const row = startRow + i;
    sheet.getRange(row, dateCol).setValue(r.date);
    sheet.getRange(row, amountCol).setValue(r.amount);
    sheet.getRange(row, payerCol).setValue(r.payer);
  });

  return parsed.length;
}
