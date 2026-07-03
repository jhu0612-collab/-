/**
 * 엑셀(거래내역) 파일을 업로드하면 "현재 열려있는(활성) 탭"에 자동으로 옮겨 적는 스크립트.
 *
 * 대상 탭이 매번 바뀌므로, 특정 gid에 고정하지 않고 실행 시점에 화면에 떠 있는
 * 탭(SpreadsheetApp.getActiveSheet())을 대상으로 삼습니다.
 * -> 실행 전에 반드시 원하는 탭을 브라우저에서 열어둔 상태로 두세요.
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
 * 모든 전역 이름에 EAI_ 접두사를 붙였고, onOpen은 정의하지 않았습니다.
 * 실행은 Apps Script 편집기 상단의 함수 선택 드롭다운에서 EAI_showUploadDialog를
 * 고른 뒤 ▶ 실행 버튼을 누르면 됩니다. (메뉴에 넣고 싶으면 이 파일 하단 안내 참고)
 */

const EAI_LAST_COL = 23; // A ~ W
const EAI_HEADER_ROW = 1;

function EAI_showUploadDialog() {
  const html = HtmlService.createHtmlOutputFromFile('UploadDialog')
    .setWidth(420)
    .setHeight(300);
  SpreadsheetApp.getUi().showModalDialog(html, '엑셀 파일 업로드');
}

function EAI_getTargetSheet_() {
  const sheet = SpreadsheetApp.getActiveSheet();
  if (!sheet) {
    throw new Error('활성 탭을 찾을 수 없습니다. 대상 탭을 열어둔 상태에서 다시 실행해주세요.');
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
 * 클라이언트(UploadDialog.html)에서 파싱한 레코드를 받아 활성 탭에 기재한다.
 * records: [{ dateStr, amount, payer }]
 * return: { sheetName, added, skipped }
 */
function EAI_importRecords(records) {
  const sheet = EAI_getTargetSheet_();
  const headerCols = EAI_findHeaderColumns_(sheet);

  const dateCol = headerCols['결제일'] || headerCols['주문일시'];
  const amountCol = headerCols['결제금액'] || headerCols['주문금액'];
  const payerCol = headerCols['구매자'] || headerCols['회원명'];

  if (!dateCol || !amountCol || !payerCol) {
    throw new Error('현재 탭("' + sheet.getName() + '")에서 결제일/결제금액/구매자(또는 주문일시/주문금액/회원명) 열을 찾을 수 없습니다.');
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
    added: newOnly.length,
    skipped: skipped
  };
}

/**
 * (선택) 메뉴 버튼으로 실행하고 싶다면, 이 프로젝트의 기존 onOpen() 함수 안에
 * 아래 한 줄을 추가하세요. 이 파일 자체에는 onOpen을 새로 만들지 않습니다
 * (기존 onOpen과 중복 선언되면 스크립트 전체가 에러로 멈춥니다).
 *
 *   ui.createMenu('엑셀 자동입력').addItem('엑셀 파일 업로드', 'EAI_showUploadDialog').addToUi();
 *
 * 기존 onOpen이 없다면 아래 함수의 이름을 onOpen으로 바꿔서 그대로 써도 됩니다.
 */
function EAI_onOpen_template_() {
  SpreadsheetApp.getUi()
    .createMenu('엑셀 자동입력')
    .addItem('엑셀 파일 업로드', 'EAI_showUploadDialog')
    .addToUi();
}
