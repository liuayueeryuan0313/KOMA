// Protocol helpers from the reviewed research package. Importing does not log in.
import {
  createCipheriv,
  createDecipheriv,
  createPublicKey,
  publicEncrypt,
  randomBytes,
  constants as C,
} from 'node:crypto';
import {schoolProfile,schoolFetch,endpoint} from './school-profile.mjs';

const TIMEOUT = 20000;

// ------------------------------------------------------------------ 加密原语

const aesEnc = (text, keyB64) => {
  const c = createCipheriv('aes-128-ecb', Buffer.from(keyB64, 'base64'), null);
  return Buffer.concat([c.update(Buffer.from(text, 'utf8')), c.final()]).toString('base64');
};

const aesDec = (b64, keyB64) => {
  const d = createDecipheriv('aes-128-ecb', Buffer.from(keyB64, 'base64'), null);
  return Buffer.concat([d.update(Buffer.from(String(b64).trim(), 'base64')), d.final()]).toString('utf8');
};

const rsaEnc = (text, pubB64) =>
  publicEncrypt(
    { key: createPublicKey({ key: Buffer.from(pubB64, 'base64'), format: 'der', type: 'spki' }), padding: C.RSA_PKCS1_PADDING },
    Buffer.from(text, 'utf8'),
  ).toString('base64');

async function post(url, body, headers = {}, fetchImpl=globalThis.fetch) {
  const res = await fetchImpl(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT),
  });
  return { status: res.status, text: await res.text() };
}

// ------------------------------------------------------------------ 第一步

/** 密钥协商：随机 AES-128 key 用服务器 RSA 公钥包上去，换回 onlyCode。 */
async function keyExchange(school=schoolProfile(),fetchImpl=schoolFetch(school,[school.app_origin,school.app_h5_base])) {
  const url = endpoint(school.app_origin,'/mobileapi_ydxy/open/security/asym/key');
  const pubRes = await fetchImpl(url, { headers: { 'Asym-Key': 'public' }, signal: AbortSignal.timeout(TIMEOUT) });
  const pubBody = JSON.parse(await pubRes.text());
  if (String(pubBody.code) !== '0') throw new Error(`取公钥失败: ${pubBody.code} ${pubBody.msg}`);

  const aesKey = randomBytes(16).toString('base64');
  const up = await post(url, rsaEnc(JSON.stringify({ sk: aesKey }), String(pubBody.data).trim()), {
    'Asym-Key': 'private',
    'content-type': 'text/plain; charset=utf-8',
  },fetchImpl);
  const upBody = JSON.parse(up.text);
  if (String(upBody.code) !== '0') throw new Error(`上传密钥失败: ${upBody.code} ${upBody.msg}`);

  // 解密结果实测是裸的 36 字符 GUID（不是 JSON），也兼容包成 JSON 的情况
  const plain = aesDec(upBody.data, aesKey).trim();
  let code = plain;
  try {
    const parsed = JSON.parse(plain);
    code = typeof parsed === 'string' ? parsed : parsed.onlyCode || parsed.onlycode || parsed.code || plain;
  } catch {
    /* 裸字符串 */
  }
  if (!code) throw new Error('onlyCode 为空');
  return { aesKey, onlyCode: code, school };
}

/** 账号密码登录，拿到会话。 */
async function login({ aesKey, onlyCode, school=schoolProfile() }, userId, password,fetchImpl=schoolFetch(school,[school.app_origin,school.app_h5_base])) {
  const head = JSON.stringify({
    clientVersion: school.app_client_version,
    sessionKey: '',
    userId: '',
    userType: '',
    xxdm: school.app_school_id,
  });
  const body = JSON.stringify({
    passw: password,
    schoolId: school.app_school_id,
    userId,
    androidClientVersionCode: '62',
    checkCode: '',
    city: '',
    clientVersion: school.app_client_version,
    deviceId: 'fetch-timetable-node',
    deviceModel: 'Android',
    deviceType: '1',
    deviceVersion: '13',
    imei: '',
    latitude: '',
    longitude: '',
    phoneNum: '',
    province: '',
    serverApiVersion: school.app_client_version,
  });
  const res = await post(endpoint(school.app_origin,'/mobileapi_ydxy/open/auth/login'), aesEnc(body, aesKey), {
    'Access-Token': aesEnc(head, aesKey),
    'Unique-Code': onlyCode,
    AppType: 'ydxy',
    'content-type': 'text/plain; charset=utf-8',
  },fetchImpl);
  const env = JSON.parse(res.text);
  if (String(env.code) !== '0') throw new Error(`登录失败: ${env.code} ${env.msg}`);
  const me = JSON.parse(aesDec(env.data, aesKey));
  if (!me.session_key) throw new Error('登录成功但没有 session_key');

  // 注意：公共头 xxdm 用的是登录返回的 schoolId（本校为 "sdut"），不是配置里的 "SDLG"
  return {
    aesKey,
    onlyCode,
    userId: me.userId || userId,
    userType: me.userType || '',
    sessionKey: me.session_key,
    xxdm: me.schoolId || school.app_school_id,
    school,
    profile: me,
  };
}

// ------------------------------------------------------------------ 第二步

/** 用内置会话换课表服务的 token。 */
async function h5Login(session,fetchImpl=schoolFetch(session.school??schoolProfile(),[(session.school??schoolProfile()).app_h5_base])) {
  const school=session.school??schoolProfile();
  const head = JSON.stringify({
    clientVersion: school.app_client_version,
    sessionKey: session.sessionKey,
    userId: session.userId,
    userType: session.userType,
    xxdm: session.xxdm,
  });
  const res = await post(endpoint(school.app_h5_base,school.app_exchange_path), {
    accessToken: aesEnc(head, session.aesKey),
    uniqueCode: session.onlyCode,
    yyid: school.app_yyid,
  },{},fetchImpl);
  const env = JSON.parse(res.text);
  if (String(env.code) !== '200') throw new Error(`换取 token 失败: ${env.code} ${env.msg}`);
  return env.data.tokenValue;
}


// --------------------------------------------------------------------- 输出


export {keyExchange, login, h5Login};
