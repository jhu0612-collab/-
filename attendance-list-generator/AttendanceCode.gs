/**
 * 알림톡 대상자 추출 스크립트.
 *
 * 클어/타이탄 두 형식을 헤더 텍스트로 자동 판별해서 하나의 메뉴로 처리한다.
 *  - 클어: 이름='구매자', 상태열='결제상태'
 *  - 타이탄: 이름='회원명', 상태열='주문상태'
 *  - 공통: 전화번호 헤더에 '전화번호' 포함(전화번호/휴대전화번호 둘 다 매칭),
 *          상태값이 '결제완료', '카톡방 입장' 체크박스가 체크 안 된 사람만 추출.
 *          이름+전화번호가 같으면(분할결제 등) 1명으로 중복 제거.
 *          '카톡방' 열 값으로 그룹을 나눠서 반별로 엑셀 파일을 만든다.
 *
 * 출력 엑셀 형식:
 *  - 클어: 시트명 '발송 데이터', 헤더 연락처/#{고객명}/#{강좌명}/#{입장코드}/#{링크명}
 *  - 타이탄: 시트명 'sheet1', 헤더 연락처/고객명/강좌명/입장코드/링크명
 *
 * 결과물은 구글 드라이브에 남기지 않고, 반별 엑셀들을 zip으로 묶어
 * 실행한 사람 브라우저에서 바로 다운로드되도록 돌려준다.
 *
 * 주의: 이 프로젝트에는 다른 스크립트(계좌이체 반영, 엑셀 자동입력 등)가 이미 있으므로
 * 모든 전역 이름에 ATT_ 접두사를 붙였고, onOpen은 정의하지 않았습니다.
 */

const ATT_PHONE_SUBSTR = '전화번호';
const ATT_STATUS_OK_VALUE = '결제완료';
const ATT_ENTRY_HEADER = '카톡방 입장';
const ATT_ROOM_HEADER = '카톡방';
const ATT_MAX_ROWS = 30;

function ATT_showDialog() {
  const html = HtmlService.createHtmlOutputFromFile('AttendanceDialog')
    .setWidth(760)
    .setHeight(600);
  SpreadsheetApp.getUi().showModalDialog(html, '알림톡 대상자 추출');
}

/**
 * 다이얼로그가 열릴 때 호출: 현재 탭 이름 + '카톡방' 열에 있는 방 이름 목록(자동완성용)을 돌려준다.
 */
function ATT_getDialogInit() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  if (data.length === 0) {
    return { sheetName: sheet.getName(), roomNames: [], maxRows: ATT_MAX_ROWS };
  }

  const header = data[0].map(function (h) { return String(h).trim(); });
  const roomCol = header.indexOf(ATT_ROOM_HEADER);

  const roomNames = [];
  if (roomCol !== -1) {
    const seen = {};
    for (let i = 1; i < data.length; i++) {
      const v = String(data[i][roomCol]).trim();
      if (v && !seen[v]) {
        seen[v] = true;
        roomNames.push(v);
      }
    }
  }

  return { sheetName: sheet.getName(), roomNames: roomNames, maxRows: ATT_MAX_ROWS };
}

/**
 * 헤더 배열에서 클어/타이탄 여부 및 필요한 열 인덱스를 찾는다.
 */
function ATT_findColumns_(header) {
  let mode = null;
  let nameCol = header.indexOf('구매자');
  if (nameCol !== -1) {
    mode = 'clear';
  } else {
    nameCol = header.indexOf('회원명');
    if (nameCol !== -1) mode = 'titan';
  }
  if (mode === null) {
    throw new Error('이름 열("구매자" 또는 "회원명")을 찾을 수 없습니다.');
  }

  let phoneCol = -1;
  for (let i = 0; i < header.length; i++) {
    if (header[i].indexOf(ATT_PHONE_SUBSTR) !== -1) {
      phoneCol = i;
      break;
    }
  }
  if (phoneCol === -1) {
    throw new Error('전화번호 열을 찾을 수 없습니다.');
  }

  const statusHeader = mode === 'clear' ? '결제상태' : '주문상태';
  const statusCol = header.indexOf(statusHeader);
  if (statusCol === -1) {
    throw new Error('"' + statusHeader + '" 열을 찾을 수 없습니다.');
  }

  const entryCol = header.indexOf(ATT_ENTRY_HEADER);
  if (entryCol === -1) {
    throw new Error('"' + ATT_ENTRY_HEADER + '" 열을 찾을 수 없습니다.');
  }

  const roomCol = header.indexOf(ATT_ROOM_HEADER);
  if (roomCol === -1) {
    throw new Error('"' + ATT_ROOM_HEADER + '" 열을 찾을 수 없습니다.');
  }

  return { mode: mode, nameCol: nameCol, phoneCol: phoneCol, statusCol: statusCol, entryCol: entryCol, roomCol: roomCol };
}

/**
 * 한국 휴대폰 번호(010/011/016/017/018/019)를 000-0000-0000 형식으로 반환한다.
 * 셀이 "숫자" 서식으로 저장된 경우 맨 앞 0이 사라지므로(예: 01090085800 -> 1090085800)
 * 셀 타입이 number이고 9~10자리면 0을 복구한 뒤 포맷한다.
 * 형식이 안 맞으면(외국 번호 등) null을 반환한다.
 */
function ATT_formatPhone_(rawCellValue) {
  let digits;
  if (typeof rawCellValue === 'number') {
    digits = String(Math.trunc(rawCellValue));
    if (digits.length === 9 || digits.length === 10) {
      digits = '0' + digits; // 숫자 서식 때문에 사라진 맨 앞 0 복구
    }
  } else {
    digits = String(rawCellValue).replace(/\D/g, '');
  }

  if (!/^01[016789]/.test(digits)) return null;
  if (digits.length === 11) {
    return digits.slice(0, 3) + '-' + digits.slice(3, 7) + '-' + digits.slice(7);
  }
  if (digits.length === 10) {
    return digits.slice(0, 3) + '-' + digits.slice(3, 6) + '-' + digits.slice(6);
  }
  return null;
}

/**
 * 현재 탭에서 조건에 맞는 사람들을 뽑아 '카톡방' 값 기준으로 묶는다.
 */
function ATT_extractByRoom_() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    throw new Error('데이터가 없습니다.');
  }

  const header = data[0].map(function (h) { return String(h).trim(); });
  const cols = ATT_findColumns_(header);

  const seenKey = {};
  const byRoom = {};
  const excluded = [];

  for (let i = 1; i < data.length; i++) {
    const row = data[i];

    const status = String(row[cols.statusCol]).trim();
    if (status !== ATT_STATUS_OK_VALUE) continue;

    const entryVal = row[cols.entryCol];
    if (entryVal === true) continue; // 이미 카톡방 입장함

    const name = String(row[cols.nameCol]).trim();
    const rawPhoneCell = row[cols.phoneCol];
    const rawPhoneStr = String(rawPhoneCell).trim();
    if (!name || !rawPhoneStr) continue;

    const key = name + '|' + rawPhoneStr;
    if (seenKey[key]) continue; // 분할결제 등으로 인한 중복 제거
    seenKey[key] = true;

    const room = String(row[cols.roomCol]).trim() || '미배정';
    const formattedPhone = ATT_formatPhone_(rawPhoneCell);

    if (formattedPhone === null) {
      // 번호 형식이 한국 휴대폰 번호가 아님 (외국인 등) -> 명단에서 제외하고 별도 보고
      excluded.push({ name: name, phone: rawPhoneStr, room: room });
      continue;
    }

    if (!byRoom[room]) byRoom[room] = [];
    byRoom[room].push({ name: name, phone: formattedPhone });
  }

  return { mode: cols.mode, sheetName: sheet.getName(), byRoom: byRoom, excluded: excluded };
}

/**
 * 반 하나 분량의 데이터로 임시 구글시트를 만들어 xlsx Blob으로 변환하고,
 * 임시 시트는 바로 휴지통으로 보낸다.
 */
function ATT_createExcelBlob_(mode, people, cfg, fileBaseName) {
  const temp = SpreadsheetApp.create(fileBaseName);
  const ss = SpreadsheetApp.openById(temp.getId());
  const sheet = ss.getSheets()[0];

  if (mode === 'clear') {
    sheet.setName('발송 데이터');
    sheet.getRange(1, 1, 1, 5).setValues([['연락처', '#{고객명}', '#{강좌명}', '#{입장코드}', '#{링크명}']]);
  } else {
    sheet.setName('sheet1');
    sheet.getRange(1, 1, 1, 5).setValues([['연락처', '고객명', '강좌명', '입장코드', '링크명']]);
  }

  if (people.length > 0) {
    const rows = people.map(function (p) {
      return [p.phone, p.name, cfg.courseName || '', cfg.entryCode || '', cfg.linkName || ''];
    });
    sheet.getRange(2, 1, rows.length, 5).setValues(rows);
  }

  SpreadsheetApp.flush();

  const exportUrl = 'https://docs.google.com/spreadsheets/d/' + temp.getId() + '/export?format=xlsx';
  const token = ScriptApp.getOAuthToken();
  const response = UrlFetchApp.fetch(exportUrl, { headers: { Authorization: 'Bearer ' + token } });
  const blob = response.getBlob().setName(fileBaseName + '.xlsx');

  DriveApp.getFileById(temp.getId()).setTrashed(true);

  return blob;
}

/**
 * 다이얼로그에서 입력한 반별 설정을 받아, 반별 엑셀들을 zip으로 묶어 base64로 돌려준다.
 * configs: [{ className, courseName, entryCode, linkName }]
 * return: {
 *   files: [{ className, count }],
 *   excluded: [{ name, phone, room }],
 *   zipBase64, zipFileName
 * }
 */
function ATT_generate(configs) {
  const validConfigs = (configs || []).filter(function (c) {
    return c.className && c.className.trim();
  });
  if (validConfigs.length === 0) {
    throw new Error('대상 반 이름을 최소 1개 이상 입력해주세요.');
  }

  const extracted = ATT_extractByRoom_();
  const results = [];
  const blobs = [];

  const classNames = validConfigs.map(function (c) { return c.className.trim(); });
  const relevantExcluded = extracted.excluded.filter(function (e) {
    return classNames.indexOf(e.room) !== -1;
  });

  validConfigs.forEach(function (cfg) {
    const className = cfg.className.trim();
    const people = extracted.byRoom[className] || [];
    const fileBaseName = '출석부_' + className;
    const blob = ATT_createExcelBlob_(extracted.mode, people, cfg, fileBaseName);
    blobs.push(blob);
    results.push({ className: className, count: people.length });
  });

  const ts = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyyMMdd_HHmmss');
  const zipBlob = Utilities.zip(blobs, '알림톡_대상자_' + ts + '.zip');

  return {
    files: results,
    excluded: relevantExcluded,
    zipBase64: Utilities.base64Encode(zipBlob.getBytes()),
    zipFileName: zipBlob.getName(),
  };
}

/**
 * (선택) 메뉴 등록용. 이미 프로젝트에 onOpen()이 있다면 그 안에 아래 한 줄만 추가하세요.
 *   ui.createMenu('알림톡 대상자 추출').addItem('명단 추출', 'ATT_showDialog').addToUi();
 * onOpen이 없다면 이 함수 이름을 onOpen으로 바꿔서 사용하세요.
 */
function ATT_onOpen_template_() {
  SpreadsheetApp.getUi()
    .createMenu('알림톡 대상자 추출')
    .addItem('명단 추출', 'ATT_showDialog')
    .addToUi();
}
