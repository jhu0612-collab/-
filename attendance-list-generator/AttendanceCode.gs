/**
 * 알림톡 대상자 추출 스크립트.
 *
 * 입력(마더시트)은 클어/타이탄 두 헤더 형식을 자동 판별해서 처리한다.
 *  - 클어: 이름='구매자', 상태열='결제상태'
 *  - 타이탄: 이름='회원명', 상태열='주문상태'
 *  - 공통: 전화번호 헤더에 '전화번호' 포함(전화번호/휴대전화번호 둘 다 매칭),
 *          상태값이 '결제완료'인 행 중, '카톡방 입장' 셀이
 *            1) 체크박스가 있고 미체크(false 또는 빈칸)인 사람만 추출.
 *            2) 체크박스 자체가 없는 완전 공란(환불자 등)은 제외.
 *            3) 체크박스가 있고 체크됨(true 또는 "입장" 같은 값)도 제외.
 *          (getDataValidations()로 체크박스 서식 유무까지 확인함 — ATT_shouldIncludeByEntry_ 참고)
 *          이름+전화번호가 같으면(분할결제 등) 1명으로 중복 제거.
 *          '카톡방' 열 값으로 그룹을 나눠서 반별로 엑셀 파일을 만든다.
 *
 * 출력(엑셀) 형식은 입력 형식과 무관하게, 다이얼로그 상단에서 고른
 * "슝슝이 / 피콘" 플랫폼에 따라 정해진다.
 *  - 슝슝이: 시트명 '발송 데이터', 헤더 연락처/#{고객명}/#{강좌명}/#{입장코드}/#{링크명}
 *  - 피콘: 시트명 'sheet1', 헤더 연락처/고객명/강좌명/입장코드/링크명
 *
 * 결과물은 구글 드라이브에 남기지 않고, 반별 엑셀 파일을 각각
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
const ATT_PLATFORMS = ['soongsoongi', 'picon'];

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
 * 셀에 체크박스 데이터 유효성 검사(서식)가 실제로 적용되어 있는지 확인한다.
 * (getValues()만으로는 "체크박스 있고 빈칸"과 "체크박스 자체가 없는 빈칸"을 구분할 수 없어서
 * getDataValidations()로 별도 확인이 필요함)
 */
function ATT_hasCheckboxValidation_(validationCell) {
  if (!validationCell) return false;
  try {
    return validationCell.getCriteriaType() === SpreadsheetApp.DataValidationCriteria.CHECKBOX;
  } catch (e) {
    return false;
  }
}

/**
 * '카톡방 입장' 셀이 명단에 포함되어야 하는지(=아직 미입장) 판정한다.
 * - 체크박스 자체가 없는 완전 공란(예: 환불자) -> 포함하지 않음(제외)
 * - 체크박스가 있고 체크됨(true 또는 "입장" 같은 비어있지 않은 커스텀 값) -> 제외
 * - 체크박스가 있고 미체크(false 또는 빈칸) -> 포함
 */
function ATT_shouldIncludeByEntry_(hasCheckbox, entryVal) {
  if (!hasCheckbox) return false;
  if (typeof entryVal === 'boolean') return entryVal === false;
  return String(entryVal).trim() === '';
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
  const range = sheet.getDataRange();
  const data = range.getValues();
  const validations = range.getDataValidations();
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

    const hasCheckbox = ATT_hasCheckboxValidation_(validations[i][cols.entryCol]);
    if (!ATT_shouldIncludeByEntry_(hasCheckbox, row[cols.entryCol])) continue;

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
 * platform: 'soongsoongi' | 'picon' - 출력 엑셀 형식을 결정한다 (입력 형식과는 무관).
 */
function ATT_createExcelBlob_(platform, people, cfg, fileBaseName) {
  const temp = SpreadsheetApp.create(fileBaseName);
  const ss = SpreadsheetApp.openById(temp.getId());
  const sheet = ss.getSheets()[0];

  // 입장코드처럼 앞자리 0이 있는 값이 숫자로 자동 변환되어 0이 사라지는 것을 방지
  // (값을 쓰기 전에 열 서식을 먼저 "일반 텍스트"로 고정해야 함)
  sheet.getRange('A:E').setNumberFormat('@');

  if (platform === 'picon') {
    sheet.setName('sheet1');
    sheet.getRange(1, 1, 1, 5).setValues([['연락처', '고객명', '강좌명', '입장코드', '링크명']]);
  } else {
    sheet.setName('발송 데이터');
    sheet.getRange(1, 1, 1, 5).setValues([['연락처', '#{고객명}', '#{강좌명}', '#{입장코드}', '#{링크명}']]);
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
 * 다이얼로그에서 보낸 설정 하나(c)로부터 반 이름 배열을 뽑아낸다.
 * 다이얼로그가 화면에서 "🔗 결합" 버튼으로 여러 반을 하나의 그룹으로 묶으면
 * c.classNames 배열로 넘어온다 (예: ["A반", "B반"]). 혹시 구버전 호출 등으로
 * c.className(쉼표 구분 문자열) 형태로 오면 그것도 지원한다.
 */
function ATT_resolveClassNames_(c) {
  if (Array.isArray(c.classNames)) {
    return c.classNames.map(function (s) { return String(s).trim(); }).filter(function (s) { return s; });
  }
  return String(c.className || '')
    .split(',')
    .map(function (s) { return s.trim(); })
    .filter(function (s) { return s; });
}

/**
 * 다이얼로그에서 입력한 반별 설정을 받아, 그룹별 엑셀 파일을 각각 base64로 돌려준다.
 * (zip으로 묶지 않고 개별 파일로 바로 다운로드하기 위함)
 * 화면에서 "🔗 결합" 버튼으로 여러 반을 하나의 그룹으로 묶으면, 그 반들의 인원을
 * 전부 합쳐서 엑셀 파일 하나로 만든다 (강좌명/입장코드/링크명은 그 그룹에 입력한
 * 값 그대로 공통 적용).
 * 합친 반 전체 인원이 0명이면 엑셀을 만들지 않고 skipped 목록으로만 보고한다.
 * platform: 'soongsoongi' | 'picon' - 출력 엑셀 형식
 * configs: [{ classNames: ['A반','B반'], courseName, entryCode, linkName }]
 * return: {
 *   files: [{ className, count, fileName, base64 }],
 *   skipped: [{ className }],
 *   excluded: [{ name, phone, room }]
 * }
 */
function ATT_generate(platform, configs) {
  if (ATT_PLATFORMS.indexOf(platform) === -1) {
    throw new Error('알 수 없는 플랫폼입니다: ' + platform);
  }

  const validConfigs = (configs || [])
    .map(function (c) {
      return { cfg: c, classNames: ATT_resolveClassNames_(c) };
    })
    .filter(function (v) { return v.classNames.length > 0; });
  if (validConfigs.length === 0) {
    throw new Error('대상 반 이름을 최소 1개 이상 입력해주세요.');
  }

  const extracted = ATT_extractByRoom_();
  const results = [];
  const skipped = [];

  const allClassNames = [];
  validConfigs.forEach(function (v) {
    v.classNames.forEach(function (n) { allClassNames.push(n); });
  });
  const relevantExcluded = extracted.excluded.filter(function (e) {
    return allClassNames.indexOf(e.room) !== -1;
  });

  validConfigs.forEach(function (v) {
    const displayName = v.classNames.join('+');
    let people = [];
    v.classNames.forEach(function (className) {
      people = people.concat(extracted.byRoom[className] || []);
    });

    if (people.length === 0) {
      skipped.push({ className: displayName });
      return;
    }

    const fileBaseName = '출석부_' + displayName;
    const blob = ATT_createExcelBlob_(platform, people, v.cfg, fileBaseName);
    results.push({
      className: displayName,
      count: people.length,
      fileName: blob.getName(),
      base64: Utilities.base64Encode(blob.getBytes()),
    });
  });

  return { files: results, skipped: skipped, excluded: relevantExcluded };
}

function ATT_showEntryCheckDialog() {
  const html = HtmlService.createHtmlOutputFromFile('EntryCheckDialog')
    .setWidth(640)
    .setHeight(700);
  SpreadsheetApp.getUi().showModalDialog(html, '입장자체크');
}

/**
 * 입장자체크 다이얼로그가 열릴 때 호출: 현재 활성 탭 이름만 돌려준다.
 */
function ATT_getActiveSheetName() {
  return SpreadsheetApp.getActiveSheet().getName();
}

/**
 * 카카오톡 "대화 내보내기" 텍스트에서 "OOO님이 들어왔습니다" / "OOO님이 나갔습니다" 시스템
 * 메시지를 파일에 나온 순서(=시간순) 그대로 전부 찾아 { type, raw } 목록으로 돌려준다.
 * 메시지 뒤에 다른 텍스트가 줄바꿈 없이 붙어 있어도(내보내기 특성상 종종 발생) 상관없이
 * "님이 들어왔습니다/나갔습니다" 직전까지만 정확히 잘라낸다.
 */
function ATT_extractSystemEvents_(rawText) {
  const events = [];
  const regex = /^(.*?)님이\s*(들어왔습니다|나갔습니다)/gm;
  let match;
  while ((match = regex.exec(rawText)) !== null) {
    const nickname = match[1].trim();
    if (!nickname) continue;
    events.push({ type: match[2] === '들어왔습니다' ? 'enter' : 'leave', raw: nickname });
  }
  return events;
}

/**
 * 카톡 닉네임 하나를 이름/전화번호뒷자리로 분리한다.
 * 예: "박보검/1234", "박보검1234", "박보검,1234" -> { name: '박보검', phoneSuffix: '1234' }
 * 번호가 없으면(예: "승연") -> { name: '승연', phoneSuffix: null }
 * 구분자 유무·이름 길이·번호 4~5자리 여부에 상관없이 동작한다.
 */
function ATT_parseNickname_(nicknameRaw) {
  const m = nicknameRaw.match(/^(.*?)[\s\/,]*([0-9]{4,5})\s*$/);
  if (m && m[1].trim()) {
    return { raw: nicknameRaw, name: m[1].trim(), phoneSuffix: m[2] };
  }
  return { raw: nicknameRaw, name: nicknameRaw.trim(), phoneSuffix: null };
}

/**
 * 체크박스를 "체크됨" 상태로 만든다. 커스텀 값(예: "입장")을 쓰는 체크박스면 그 값을,
 * 표준 불리언 체크박스면 true를 넣는다.
 */
function ATT_writeCheckedValue_(range, validationCell) {
  const criteriaValues = validationCell.getCriteriaValues();
  if (criteriaValues && criteriaValues.length >= 1) {
    range.setValue(criteriaValues[0]);
  } else {
    range.setValue(true);
  }
}

function ATT_personInfo_(r) {
  return { name: r.name, last4: r.phoneDigits.slice(-4), fullPhone: r.phoneDisplay, sheetRow: r.sheetRow };
}

/**
 * 반(카톡방)별로 카카오톡 대화 내보내기 원본 텍스트를 받아, 입장/퇴장 로그를 처리해서
 * 매출시트 기준으로 분류한다.
 * roomConfigs: [{ roomName, fileText }]  // roomName = 시트 '카톡방' 열 값과 맞춰야 함
 *
 * 매칭 대상은 결제상태가 정확히 '결제완료'인 행만 (명단추출 기능과 동일한 규칙 —
 * 환불 행은 나중에 재결제로 다른 행이 결제완료가 되어도 그 환불 행 자체는 대상에서 제외).
 * 시트 전체(모든 반)를 대상으로 검색하므로, 다른 반 파일에서 매칭되면 "방 불일치"로 잡힌다.
 *
 * 매칭 규칙: 카톡 닉네임에 전화번호 뒷자리(4~5자리)가 있고, 그 번호와 이름이 모두
 * 일치하는 시트 행이 있을 때만 그 사람으로 확정한다 (체크 여부 무관하게 검색 대상).
 * 번호가 없는 닉네임은 아예 매칭을 시도하지 않고 "명단 외 입장자"로만 취급한다.
 * 후보가 0명이면 "명단 외 입장자"로 취급한다. 후보가 여럿이어도 전부 이름+전화번호가
 * 완전히 같으면(분할결제 등으로 같은 사람이 여러 행에 걸쳐 있는 경우) 동명이인이 아니라
 * 같은 사람으로 보고 그 행들을 전부 확정 처리한다. 서로 다른 이름+전화번호 조합이 섞여서
 * 매칭됐을 때만 진짜 동명이인으로 보고 "명단 외 입장자"로 취급한다.
 *
 * 매칭된 사람의 시트상 배정 반('카톡방' 열 값)이 지금 처리 중인 파일의 반 이름과
 * 다르면, 그 사람은 "다른 반에 잘못 입장한 사람"(mismatches)으로 별도 보고하고
 * 정상 입장자 체크 대상에서는 제외한다.
 *
 * 같은 사람이 자기 반 파일 안에서 입장/퇴장을 반복하면, 가장 마지막(시간상 최신)
 * 이벤트를 최종 상태로 본다 (나갔다가 재입장하면 최종은 '입장').
 *
 * 시트에는 아무 것도 기록하지 않는다(분석만). 실제로 체크박스에 반영하려면
 * 이 결과의 entered 목록에서 sheetRow 번호들을 뽑아 ATT_applyEntryChecks()를 별도로 호출해야 한다.
 *
 * return: {
 *   sheetName,
 *   pendingCount, enterLogCount, leaveLogCount,
 *   entered: [{name,last4,fullPhone,sheetRow,alreadyChecked}],   // 최종 상태: 입장 (자기 반)
 *   left: [{name,last4,fullPhone,sheetRow,alreadyChecked}],      // 최종 상태: 퇴장 (자기 반, 정보 표시용)
 *   notAppeared: [{name,last4,fullPhone,sheetRow}],  // 자기 반 파일이 제공됐는데도 등장하지 않은 사람
 *   outsideEntrants: [{raw, room, reason}, ...],      // 시트와 확정 매칭 안 된 입장 기록 + 실패 사유
 *   mismatches: [{name,last4,fullPhone,assignedRoom,enteredRoom,sheetRow}] // 다른 반에 입장한 사람
 * }
 */
function ATT_checkEntrants(roomConfigs) {
  const sheet = SpreadsheetApp.getActiveSheet();
  const range = sheet.getDataRange();
  const data = range.getValues();
  const validations = range.getDataValidations();
  if (data.length < 2) {
    throw new Error('데이터가 없습니다.');
  }

  const header = data[0].map(function (h) { return String(h).trim(); });
  const cols = ATT_findColumns_(header);

  const sheetRows = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    const name = String(row[cols.nameCol]).trim();
    if (!name) continue;

    // 명단추출 기능과 동일한 규칙: 결제상태가 정확히 '결제완료'인 행만 유효한 대상으로 본다.
    const status = String(row[cols.statusCol]).trim();
    if (status !== ATT_STATUS_OK_VALUE) continue;

    const validationCell = validations[i][cols.entryCol];
    const hasCheckbox = ATT_hasCheckboxValidation_(validationCell);
    const isPendingEntry = ATT_shouldIncludeByEntry_(hasCheckbox, row[cols.entryCol]);

    const rawPhoneCell = row[cols.phoneCol];
    const formatted = ATT_formatPhone_(rawPhoneCell);
    const phoneDisplay = formatted || String(rawPhoneCell).trim();
    const phoneDigits = formatted ? formatted.replace(/\D/g, '') : String(rawPhoneCell).replace(/\D/g, '');

    sheetRows.push({
      sheetRow: i + 1, // 실제 시트 행 번호(1-based)
      name: name,
      phoneDigits: phoneDigits,
      phoneDisplay: phoneDisplay,
      assignedRoom: String(row[cols.roomCol]).trim(),
      hasCheckbox: hasCheckbox,
      isPendingEntry: isPendingEntry,
      finalState: null, // 'enter' | 'leave' | null
    });
  }

  const pendingCount = sheetRows.filter(function (r) { return r.isPendingEntry; }).length;

  const validConfigs = (roomConfigs || []).filter(function (c) {
    return c.roomName && c.roomName.trim() && c.fileText;
  });
  if (validConfigs.length === 0) {
    throw new Error('반 이름과 카톡 대화 파일을 최소 1개 이상 입력해주세요.');
  }

  const providedRoomNames = {};
  validConfigs.forEach(function (c) { providedRoomNames[c.roomName.trim()] = true; });

  let enterLogCount = 0;
  let leaveLogCount = 0;
  const outsideEntrantsMap = {}; // "반|닉네임" -> {raw, room, reason}
  const mismatchList = [];

  validConfigs.forEach(function (cfg) {
    const roomName = cfg.roomName.trim();
    const events = ATT_extractSystemEvents_(cfg.fileText);
    enterLogCount += events.filter(function (e) { return e.type === 'enter'; }).length;
    leaveLogCount += events.filter(function (e) { return e.type === 'leave'; }).length;

    events.forEach(function (evt) {
      const parsed = ATT_parseNickname_(evt.raw);

      if (!parsed.phoneSuffix) {
        if (evt.type === 'enter') {
          outsideEntrantsMap[roomName + '|' + evt.raw] = { raw: evt.raw, room: roomName, reason: '번호 없음(매칭 시도 안 함)' };
        }
        return; // 번호 없는 닉네임은 매칭 시도 자체를 하지 않는다
      }

      const nameNorm = parsed.name.replace(/\s+/g, '');
      // 체크 여부·배정 반과 상관없이(이미 체크된 사람, 다른 반 배정자도 포함) 시트 전체에서
      // 이름+번호로 먼저 매칭한다. 그래야 방 불일치(다른 반에 잘못 입장) 감지가 가능하다.
      const candidates = sheetRows.filter(function (r) {
        if (!r.hasCheckbox) return false; // 체크박스 자체가 없는 행(환불자 등)은 매칭 대상에서 제외
        const sheetNameNorm = r.name.replace(/\s+/g, '');
        if (!sheetNameNorm || !nameNorm) return false;
        const nameMatches = sheetNameNorm.indexOf(nameNorm) !== -1 || nameNorm.indexOf(sheetNameNorm) !== -1;
        if (!nameMatches) return false;
        return r.phoneDigits.length >= parsed.phoneSuffix.length &&
          r.phoneDigits.slice(-parsed.phoneSuffix.length) === parsed.phoneSuffix;
      });

      if (candidates.length === 0) {
        if (evt.type === 'enter') {
          outsideEntrantsMap[roomName + '|' + evt.raw] = { raw: evt.raw, room: roomName, reason: '매칭 실패 (결제완료+체크박스 있는 행 중 이름·번호 일치하는 행 없음)' };
        }
        return;
      }

      // 후보가 여럿이어도 전부 이름+전화번호가 완전히 같다면(분할결제 등으로 같은 사람이
      // 시트에 여러 행으로 나뉜 경우) 동명이인이 아니라 "같은 사람"이므로 전부 확정 처리한다.
      const distinctKeys = {};
      candidates.forEach(function (c) { distinctKeys[c.name + '|' + c.phoneDigits] = true; });

      if (Object.keys(distinctKeys).length !== 1) {
        if (evt.type === 'enter') {
          outsideEntrantsMap[roomName + '|' + evt.raw] = { raw: evt.raw, room: roomName, reason: '동명이인 등 후보 여럿: ' + Object.keys(distinctKeys).join(' / ') };
        }
        return;
      }

      const assignedRoom = candidates[0].assignedRoom;

      if (assignedRoom === roomName) {
        candidates.forEach(function (c) { c.finalState = evt.type; }); // 시간순 처리이므로 마지막에 덮어써진 값이 최종 상태
      } else if (evt.type === 'enter') {
        // 시트엔 다른 반으로 배정되어 있는데, 이 반의 파일에서 입장이 확인된 경우
        mismatchList.push({
          name: candidates[0].name,
          last4: candidates[0].phoneDigits.slice(-4),
          fullPhone: candidates[0].phoneDisplay,
          assignedRoom: assignedRoom || '(미배정)',
          enteredRoom: roomName,
          sheetRow: candidates[0].sheetRow,
        });
      }
    });
  });

  const entered = sheetRows.filter(function (r) { return r.finalState === 'enter'; });
  const left = sheetRows.filter(function (r) { return r.finalState === 'leave'; });
  const notAppeared = sheetRows.filter(function (r) {
    return r.isPendingEntry && r.finalState === null && providedRoomNames[r.assignedRoom];
  });

  function toInfo(r) {
    const info = ATT_personInfo_(r);
    info.alreadyChecked = !r.isPendingEntry;
    return info;
  }

  const outsideEntrants = Object.keys(outsideEntrantsMap).map(function (k) { return outsideEntrantsMap[k]; });

  const seenMismatch = {};
  const mismatches = mismatchList.filter(function (m) {
    const key = m.sheetRow + '|' + m.enteredRoom;
    if (seenMismatch[key]) return false;
    seenMismatch[key] = true;
    return true;
  });

  return {
    sheetName: sheet.getName(),
    pendingCount: pendingCount,
    enterLogCount: enterLogCount,
    leaveLogCount: leaveLogCount,
    entered: entered.map(toInfo),
    left: left.map(toInfo),
    notAppeared: notAppeared.map(toInfo),
    outsideEntrants: outsideEntrants,
    mismatches: mismatches,
  };
}

/**
 * ATT_checkEntrants()가 분석한 "입장자" 목록의 시트 행 번호들을 받아,
 * 실제로 '카톡방 입장' 체크박스를 체크 처리한다 (이 함수를 호출해야만 시트가 바뀐다).
 * 이미 체크되어 있는 행에 다시 써도 무해하다.
 * return: { appliedCount }
 */
function ATT_applyEntryChecks(sheetRowNumbers) {
  const sheet = SpreadsheetApp.getActiveSheet();
  const lastCol = sheet.getLastColumn();
  const header = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(function (h) { return String(h).trim(); });
  const cols = ATT_findColumns_(header);

  let appliedCount = 0;
  (sheetRowNumbers || []).forEach(function (rowNum) {
    const cell = sheet.getRange(rowNum, cols.entryCol + 1);
    const validationCell = cell.getDataValidation();
    if (validationCell && ATT_hasCheckboxValidation_(validationCell)) {
      ATT_writeCheckedValue_(cell, validationCell);
      appliedCount++;
    }
  });

  return { appliedCount: appliedCount };
}

/**
 * (선택) 메뉴 등록용. 이미 프로젝트에 onOpen()이 있다면 그 안에 아래 두 줄만 추가하세요.
 *   ui.createMenu('피슝이').addItem('명단 추출', 'ATT_showDialog').addItem('입장자체크', 'ATT_showEntryCheckDialog').addToUi();
 * onOpen이 없다면 이 함수 이름을 onOpen으로 바꿔서 사용하세요.
 */
function ATT_onOpen_template_() {
  SpreadsheetApp.getUi()
    .createMenu('피슝이')
    .addItem('명단 추출', 'ATT_showDialog')
    .addItem('입장자체크', 'ATT_showEntryCheckDialog')
    .addToUi();
}
