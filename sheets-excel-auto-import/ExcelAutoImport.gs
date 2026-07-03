/**
 * 엑셀(거래내역) 파일을 업로드하면, 업로드 창에서 직접 고른 탭에 자동으로 옮겨 적는 스크립트.
 *
 * 대상 탭이 매번 바뀌므로 gid나 "활성 탭 자동 인식" 대신, 업로드 창의 드롭다운에서
 * 사람이 눈으로 보고 탭을 직접 선택하게 합니다. (자동 인식은 실행 방식에 따라
 * 브라우저의 "마지막으로 본 탭"을 정확히 못 잡는 경우가 있어 신뢰할 수 없었음)
 *
 * 매핑 규칙
 *  - 엑셀 '일시'      -> 시트 '결제일'   (없으면 '주문일시')
 *  - 엑셀 '금액'      -> 시트 '결제금액' (없으면 '주문금액')
 *  - 엑셀 '계좌적요'  -> 시트 '구매자'   (없으면 '회원명')
 *
 * 규칙
 *  - 금액이 음수(환불/이체)인 행은 제외
 *  - 이미 시트에 동일한 (결제일+결제금액+구매자) 조합이 있으면 중복으로 보고 건너뜀
 *  - '일시' 기준 오름차순 정렬 후 기재
 *  - A~W열이 전부 비어있는 첫 행부터 순서대로 기재 (그 위에 이미 있는 값은 건드리지 않음)
 *
 * 주의: 이 프로젝트에는 다른 스크립트(free-lecture-bot.gs 등)가 이미 있을 수 있으므로
 * 모든 전역 이름에 EAI_ 접두사를 붙였습니다.
 */

const EAI_LAST_COL = 23; // A ~ W
const EAI_HEADER_ROW = 1;

function EAI_showUploadDialog() {
  const html = HtmlService.createHtmlOutputFromFile('UploadDialog')
    .setWidth(420)
    .setHeight(340);
  SpreadsheetApp.getUi().showModalDialog(html, '엑셀 파일 업로드');
}

/**
 * 업로드 창이 열릴 때 호출됨: 선택 가능한 탭 목록 + 추천값(현재 활성 탭)을 돌려준다.
 */
function EAI_getDialogInit() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetNames = ss.getSheets().map(function (sh) {
    return sh.getName();
  });

  let suggested = '';
  try {
    const active = SpreadsheetApp.getActiveSheet();
    if (active) suggested = active.getName();
  } catch (e) {
    // 활성 탭을 못 가져와도 무시하고 목록만 보여준다.
  }

  return { sheetNames: sheetNames, suggested: suggested };
}

function EAI_getTargetSheet_(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    throw new Error('"' + sheetName + '" 탭을 찾을 수 없습니다.');
  }
  return sheet;
}

function EAI_findHeaderColumns_(sheet) {
  const headerValues = sheet.getRange(EAI_HEADER_ROW, 1, 1, EAI_LAST_COL).getValues()[0];
  const result = {};
  headerValues.forEach(function (h, idx) {
    const name = String(h).trim();
    if (name) result[name] = idx + 1; // 1-based column index
  });
  return result;
}

function EAI_findFirstBlankRow_(sheet) {
  const lastRow = Math.max(sheet.getLastRow(), EAI_HEADER_ROW);
  const scanRows = lastRow - EAI_HEADER_ROW + 1;
  if (scanRows <= 0) return EAI_HEADER_ROW + 1;

  const values = sheet.getRange(EAI_HEADER_ROW + 1, 1, scanRows, EAI_LAST_COL).getValues();
  for (let i = 0; i < values.length; i++) {
    const isBlank = values[i].every(function (cell) {
      return cell === '' || cell === null;
    });
    if (isBlank) return EAI_HEADER_ROW + 1 + i;
  }
  return lastRow + 1;
}

function EAI_makeKey_(date, amount, payer) {
  const t = date instanceof Date ? date.getTime() : new Date(date).getTime();
  return t + '|' + Number(amount) + '|' + String(payer).trim();
}

function EAI_loadExistingKeys_(sheet, dateCol, amountCol, payerCol) {
  const lastRow = sheet.getLastRow();
  const keys = new Set();
  const existingRows = lastRow - EAI_HEADER_ROW;
  if (existingRows <= 0) return keys;

  const dateVals = sheet.getRange(EAI_HEADER_ROW + 1, dateCol, existingRows, 1).getValues();
  const amountVals = sheet.getRange(EAI_HEADER_ROW + 1, amountCol, existingRows, 1).getValues();
  const payerVals = sheet.getRange(EAI_HEADER_ROW + 1, payerCol, existingRows, 1).getValues();

  for (let i = 0; i < existingRows; i++) {
    const d = dateVals[i][0];
    const a = amountVals[i][0];
    const p = payerVals[i][0];
    if (d instanceof Date && a !== '' && a !== null && p !== '' && p !== null) {
      keys.add(EAI_makeKey_(d, a, p));
    }
  }
  return keys;
}

/**
 * 클라이언트(UploadDialog.html)에서 파싱한 레코드를 받아, 사용자가 고른 탭에 기재한다.
 * records: [{ dateStr, amount, payer }]
 * sheetName: 드롭다운에서 선택한 탭 이름
 * return: { sheetName, added, skipped }
 */
function EAI_importRecords(records, sheetName) {
  const sheet = EAI_getTargetSheet_(sheetName);
  const headerCols = EAI_findHeaderColumns_(sheet);

  const dateCol = headerCols['결제일'] || headerCols['주문일시'];
  const amountCol = headerCols['결제금액'] || headerCols['주문금액'];
  const payerCol = headerCols['구매자'] || headerCols['회원명'];

  if (!dateCol || !amountCol || !payerCol) {
    throw new Error('"' + sheet.getName() + '" 탭에서 결제일/결제금액/구매자(또는 주문일시/주문금액/회원명) 열을 찾을 수 없습니다.');
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

  const existingKeys = EAI_loadExistingKeys_(sheet, dateCol, amountCol, payerCol);
  const newOnly = parsed.filter(function (r) {
    return !existingKeys.has(EAI_makeKey_(r.date, r.amount, r.payer));
  });
  const skipped = parsed.length - newOnly.length;

  const startRow = EAI_findFirstBlankRow_(sheet);

  newOnly.forEach(function (r, i) {
    const row = startRow + i;
    sheet.getRange(row, dateCol).setValue(r.date);
    sheet.getRange(row, amountCol).setValue(r.amount);
    sheet.getRange(row, payerCol).setValue(r.payer);
  });

  return {
    sheetName: sheet.getName(),
    startRow: startRow,
    added: newOnly.length,
    skipped: skipped
  };
}

/**
 * 시트 메뉴에 등록하고 싶다면, 이 프로젝트에 onOpen() 함수가 없을 경우
 * 아래 함수 이름을 onOpen으로 바꿔서 사용하세요. 이미 onOpen이 있다면
 * 그 안에 createMenu(...).addItem(...).addToUi(); 한 줄만 옮겨 붙이세요.
 */
function EAI_onOpen_template_() {
  SpreadsheetApp.getUi()
    .createMenu('계좌이체 반영')
    .addItem('엑셀 파일 업로드', 'EAI_showUploadDialog')
    .addToUi();
}
