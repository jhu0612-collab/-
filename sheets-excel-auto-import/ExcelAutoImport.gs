/**
 * 엑셀(거래내역) 파일을 업로드하면, 업로드 창에서 직접 고른 탭에 자동으로 옮겨 적는 스크립트.
 *
 * 대상 탭이 매번 바뀌므로 gid나 "활성 탭 자동 인식" 대신, 업로드 창의 드롭다운에서
 * 사람이 눈으로 보고 탭을 직접 선택하게 합니다. (자동 인식은 실행 방식에 따라
 * 브라우저의 "마지막으로 본 탭"을 정확히 못 잡는 경우가 있어 신뢰할 수 없었음)
 *
 * 매핑 규칙
 *  - 엑셀 '일시'      -> 시트 '결제일'   (없으면 '주문일시') / 표시형식 yyyy-mm-dd hh:mm 로 강제
 *  - 엑셀 '금액'      -> 시트 '결제금액' (없으면 '주문금액')
 *  - 엑셀 '계좌적요'  -> 시트 '구매자'   (없으면 '회원명')
 *  - 고정값 '계좌이체' -> 시트 '결제수단' (없으면 '결제방법') (해당 열이 있을 때만)
 *  - 고정값 '결제완료' -> 시트 '결제상태' (없으면 '주문상태') (해당 열이 있을 때만)
 *  - 고정값 '강의'     -> 시트 '상품유형' (해당 열이 있을 때만)
 *  - 고정값 '면세'     -> 시트 '면세여부' (해당 열이 있을 때만)
 *
 * 규칙
 *  - 금액이 음수(환불/이체)인 행은 제외
 *  - 이미 시트에 동일한 (결제일+결제금액+구매자) 조합이 있으면 중복으로 보고 건너뜀
 *  - '일시' 기준 오름차순 정렬 후 기재
 *  - 결제일/결제금액/구매자 3개 열이 모두 비어있는 첫 행부터 순서대로 기재.
 *    (전체 A~W가 아니라 이 3개 열만 봄 — 번호 열이나 체크박스 등 다른 열에
 *    템플릿 값이 미리 채워져 있어도 무시하고, 실제로 쓸 칸만 비어있으면 그 자리에 기재)
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

function EAI_isCellBlank_(v) {
  return v === '' || v === null || (typeof v === 'string' && v.trim() === '');
}

/**
 * cols에 지정된 열들만 확인해서, 그 열들이 전부 비어있는 첫 행을 찾는다.
 * (다른 열의 박스 테두리/서식/번호/체크박스 등은 무시)
 */
function EAI_findFirstBlankRow_(sheet, cols) {
  const lastRow = Math.max(sheet.getLastRow(), EAI_HEADER_ROW);
  const scanRows = lastRow - EAI_HEADER_ROW + 1;
  if (scanRows <= 0) return EAI_HEADER_ROW + 1;

  const colValues = cols.map(function (col) {
    return sheet.getRange(EAI_HEADER_ROW + 1, col, scanRows, 1).getValues();
  });

  for (let i = 0; i < scanRows; i++) {
    const isBlank = colValues.every(function (vals) {
      return EAI_isCellBlank_(vals[i][0]);
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
  const methodCol = headerCols['결제수단'] || headerCols['결제방법'];
  const statusCol = headerCols['결제상태'] || headerCols['주문상태'];
  const productTypeCol = headerCols['상품유형'];
  const taxCol = headerCols['면세여부'];

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

  const startRow = EAI_findFirstBlankRow_(sheet, [dateCol, amountCol, payerCol]);

  newOnly.forEach(function (r, i) {
    const row = startRow + i;
    sheet.getRange(row, dateCol).setValue(r.date).setNumberFormat('yyyy-mm-dd hh:mm');
    sheet.getRange(row, amountCol).setValue(r.amount);
    sheet.getRange(row, payerCol).setValue(r.payer);
    if (methodCol) sheet.getRange(row, methodCol).setValue('계좌이체');
    if (statusCol) sheet.getRange(row, statusCol).setValue('결제완료');
    if (productTypeCol) sheet.getRange(row, productTypeCol).setValue('강의');
    if (taxCol) sheet.getRange(row, taxCol).setValue('면세');
  });

  return {
    sheetName: sheet.getName(),
    startRow: startRow,
    added: newOnly.length,
    skipped: skipped
  };
}

/**
 * 시트 메뉴 등록용 onOpen. 이 프로젝트에 다른 onOpen()이 이미 있다면
 * 이 함수 전체를 지우고, 그 기존 onOpen() 안에 아래 한 줄만 옮겨 붙이세요.
 *   SpreadsheetApp.getUi().createMenu('계좌이체 반영').addItem('엑셀 파일 업로드', 'EAI_showUploadDialog').addToUi();
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('계좌이체 반영')
    .addItem('엑셀 파일 업로드', 'EAI_showUploadDialog')
    .addToUi();
}
