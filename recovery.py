"""Two optional security questions, salted scrypt hashes, never plaintext answers."""
import base64
import hashlib
import hmac
import secrets
import unicodedata

QUESTIONS=(
    ('first_pet','你第一只宠物的名字是什么？'),
    ('primary_teacher','你小学班主任的名字是什么？'),
    ('childhood_friend','你童年好友的名字是什么？'),
    ('birth_city','你出生的城市是哪里？'),
    ('favorite_book','你小时候最喜欢的一本书是什么？'),
    ('first_school','你就读的第一所学校叫什么？'),
)
QUESTION_LABELS=dict(QUESTIONS)
FAILURE='账户名或密保答案不正确，或该账户尚未设置密保'
DUMMY_HASH=base64.b64encode(b'0'*80).decode()


def normalized_answer(value):
    if not isinstance(value,str) or len(value)>256:raise ValueError('密保答案须为2–128个字符')
    answer=' '.join(unicodedata.normalize('NFKC',value).casefold().split())
    if not 2<=len(answer)<=128:raise ValueError('密保答案须为2–128个字符')
    return answer


def answer_digest(answer,salt):
    return hashlib.scrypt(('koma-recovery-v1\0'+answer).encode(),salt=salt,n=16384,r=8,p=1,maxmem=64*1024*1024)


def prepare_recovery(entries):
    if entries is None:return None
    if not isinstance(entries,list) or len(entries)!=2:raise ValueError('请选择两道不同的密保问题并填写答案')
    questions=[];hashes=[]
    for entry in entries:
        if not isinstance(entry,dict):raise ValueError('密保格式无效')
        question=entry.get('question')
        if not isinstance(question,str) or question not in QUESTION_LABELS or question in questions:raise ValueError('请选择两道不同的密保问题')
        answer=normalized_answer(entry.get('answer'))
        salt=secrets.token_bytes(16)
        questions.append(question);hashes.append(base64.b64encode(salt+answer_digest(answer,salt)).decode())
    return questions,hashes


def public_questions(username,questions=None):
    # Unknown, disabled and administrator accounts get the same response shape.
    # Only a successful answer check confirms an account is recoverable.
    if questions is None:
        number=int.from_bytes(hashlib.sha256(username.casefold().encode()).digest()[:4],'big')
        first=number%len(QUESTIONS);second=(first+1+number%(len(QUESTIONS)-1))%len(QUESTIONS)
        questions=[QUESTIONS[first][0],QUESTIONS[second][0]]
    return [{'id':key,'label':QUESTION_LABELS[key]} for key in questions]


def check_answers(questions,hashes,entries):
    valid=isinstance(entries,list) and len(entries)==2
    submitted=entries if valid else [{},{}]
    for index in range(2):
        entry=submitted[index] if isinstance(submitted[index],dict) else {}
        try:answer=normalized_answer(entry.get('answer'))
        except ValueError:answer='invalid-answer';valid=False
        blob=base64.b64decode(hashes[index])
        matches=hmac.compare_digest(answer_digest(answer,blob[:16]),blob[16:])
        valid=matches and entry.get('question')==questions[index] and valid
    return valid
