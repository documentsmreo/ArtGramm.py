#!/usr/bin/env python3
"""
ArtGramm - полный клон Telegram
Запуск: python artgramm.py
Открыть: http://localhost:5000
Админ: http://localhost:5000 → войти как admin/admin123
"""

from flask import Flask, request, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from datetime import datetime, timedelta
import hashlib, os, json, base64, io, uuid, time, threading
import requests as req

app = Flask(__name__)
app.secret_key = os.urandom(32).hex()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///artgramm.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
CORS(app)

GROQ_API_KEY = "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".replace(" ", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ─────────────────────────── MODELS ───────────────────────────

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    display_name = db.Column(db.String(128), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    bio = db.Column(db.Text, default='')
    avatar_b64 = db.Column(db.Text, default='')
    avatar_color = db.Column(db.String(16), default='#2AABEE')
    is_admin = db.Column(db.Boolean, default=False)
    is_bot = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    badge = db.Column(db.String(32), default='')  # official, scam, verified, fake
    label_color = db.Column(db.String(16), default='')
    online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    phone = db.Column(db.String(32), default='')
    two_fa = db.Column(db.Boolean, default=False)
    # Bot fields
    bot_description = db.Column(db.Text, default='')
    bot_appearance = db.Column(db.Text, default='')
    bot_personality = db.Column(db.Text, default='')
    bot_scenario = db.Column(db.Text, default='')
    bot_traits = db.Column(db.Text, default='[]')  # JSON list
    bot_owner_id = db.Column(db.Integer, default=0)
    bot_rating = db.Column(db.Float, default=0.0)
    bot_chat_count = db.Column(db.Integer, default=0)
    pinned = db.Column(db.Boolean, default=False)  # pinned in all chats

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(16), default='private')  # private, group, channel
    name = db.Column(db.String(128), default='')
    avatar_b64 = db.Column(db.Text, default='')
    avatar_color = db.Column(db.String(16), default='#2AABEE')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_text = db.Column(db.Text, default='')
    last_message_time = db.Column(db.DateTime, default=datetime.utcnow)
    pinned = db.Column(db.Boolean, default=False)
    muted = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text, default='')
    invite_link = db.Column(db.String(64), default='')
    members_count = db.Column(db.Integer, default=2)

class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(16), default='member')  # owner, admin, member
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    unread_count = db.Column(db.Integer, default=0)
    is_pinned = db.Column(db.Boolean, default=False)
    is_muted = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, default='')
    media_b64 = db.Column(db.Text, default='')
    media_type = db.Column(db.String(16), default='')  # image, file, sticker
    file_name = db.Column(db.String(256), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    edited = db.Column(db.Boolean, default=False)
    deleted = db.Column(db.Boolean, default=False)
    reply_to_id = db.Column(db.Integer, default=0)
    forwarded_from = db.Column(db.String(128), default='')
    reactions = db.Column(db.Text, default='{}')  # JSON
    read_by = db.Column(db.Text, default='[]')  # JSON list of user_ids
    pinned = db.Column(db.Boolean, default=False)

class BotConversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    bot_id = db.Column(db.Integer, nullable=False)
    history = db.Column(db.Text, default='[]')  # JSON list of {role, content}
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class Broadcast(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_count = db.Column(db.Integer, default=0)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(128), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed = db.Column(db.Boolean, default=False)

# ─────────────────────────── HELPERS ───────────────────────────

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def get_current_user():
    uid = session.get('user_id')
    if not uid: return None
    return User.query.get(uid)

def user_to_dict(u, include_private=False):
    d = {
        'id': u.id, 'username': u.username, 'display_name': u.display_name,
        'bio': u.bio, 'avatar_b64': u.avatar_b64, 'avatar_color': u.avatar_color,
        'is_bot': u.is_bot, 'is_admin': u.is_admin, 'badge': u.badge,
        'label_color': u.label_color, 'online': u.online,
        'last_seen': u.last_seen.isoformat() if u.last_seen else None,
        'created_at': u.created_at.isoformat() if u.created_at else None,
        'pinned': u.pinned, 'is_banned': u.is_banned,
        'bot_description': u.bot_description, 'bot_appearance': u.bot_appearance,
        'bot_personality': u.bot_personality, 'bot_scenario': u.bot_scenario,
        'bot_traits': json.loads(u.bot_traits or '[]'),
        'bot_owner_id': u.bot_owner_id, 'bot_rating': u.bot_rating,
        'bot_chat_count': u.bot_chat_count,
    }
    if include_private:
        d['phone'] = u.phone
        d['two_fa'] = u.two_fa
    return d

def msg_to_dict(m):
    sender = User.query.get(m.sender_id)
    reply = None
    if m.reply_to_id:
        rm = Message.query.get(m.reply_to_id)
        if rm:
            rs = User.query.get(rm.sender_id)
            reply = {'id': rm.id, 'text': rm.text[:80], 'sender_name': rs.display_name if rs else ''}
    return {
        'id': m.id, 'chat_id': m.chat_id,
        'sender_id': m.sender_id,
        'sender_name': sender.display_name if sender else 'Удалён',
        'sender_username': sender.username if sender else '',
        'sender_avatar': sender.avatar_b64 if sender else '',
        'sender_avatar_color': sender.avatar_color if sender else '#999',
        'sender_badge': sender.badge if sender else '',
        'text': m.text, 'media_b64': m.media_b64, 'media_type': m.media_type,
        'file_name': m.file_name,
        'created_at': m.created_at.isoformat(),
        'edited': m.edited, 'deleted': m.deleted,
        'reply_to': reply, 'forwarded_from': m.forwarded_from,
        'reactions': json.loads(m.reactions or '{}'),
        'read_by': json.loads(m.read_by or '[]'),
        'pinned': m.pinned,
    }

def chat_to_dict(c, user_id):
    member = ChatMember.query.filter_by(chat_id=c.id, user_id=user_id).first()
    # For private chats, get other user's info
    other_user = None
    display_name = c.name
    display_avatar = c.avatar_b64
    display_color = c.avatar_color
    is_bot = False
    badge = ''
    if c.type == 'private':
        other_m = ChatMember.query.filter(ChatMember.chat_id==c.id, ChatMember.user_id!=user_id).first()
        if other_m:
            ou = User.query.get(other_m.user_id)
            if ou:
                other_user = {'id': ou.id, 'username': ou.username}
                display_name = ou.display_name
                display_avatar = ou.avatar_b64
                display_color = ou.avatar_color
                is_bot = ou.is_bot
                badge = ou.badge
    unread = member.unread_count if member else 0
    is_pinned = member.is_pinned if member else False
    is_muted = member.is_muted if member else False
    return {
        'id': c.id, 'type': c.type, 'name': display_name,
        'avatar_b64': display_avatar, 'avatar_color': display_color,
        'last_message_text': c.last_message_text,
        'last_message_time': c.last_message_time.isoformat() if c.last_message_time else None,
        'unread_count': unread, 'is_pinned': is_pinned, 'is_muted': is_muted,
        'pinned': c.pinned, 'is_bot': is_bot, 'badge': badge,
        'other_user': other_user, 'members_count': c.members_count,
        'description': c.description, 'invite_link': c.invite_link,
    }

def get_or_create_private_chat(user_id, target_id):
    # Find existing
    my_chats = [m.chat_id for m in ChatMember.query.filter_by(user_id=user_id).all()]
    their_chats = [m.chat_id for m in ChatMember.query.filter_by(user_id=target_id).all()]
    for cid in my_chats:
        if cid in their_chats:
            c = Chat.query.get(cid)
            if c and c.type == 'private':
                return c
    # Create new
    c = Chat(type='private', last_message_time=datetime.utcnow())
    db.session.add(c)
    db.session.flush()
    db.session.add(ChatMember(chat_id=c.id, user_id=user_id))
    db.session.add(ChatMember(chat_id=c.id, user_id=target_id))
    db.session.commit()
    return c

def groq_chat(bot: User, history: list, user_msg: str) -> str:
    system = f"""Ты — {bot.display_name} (@{bot.username}).
Описание: {bot.bot_description}
Внешность: {bot.bot_appearance}
Характер и личность: {bot.bot_personality}
Сценарий и обстановка: {bot.bot_scenario}
Черты характера: {', '.join(json.loads(bot.bot_traits or '[]'))}

Отвечай строго в роли этого персонажа. Пиши живо, по-человечески. Не выходи из роли."""
    msgs = [{"role": "system", "content": system}]
    for h in history[-20:]:
        msgs.append(h)
    msgs.append({"role": "user", "content": user_msg})
    try:
        resp = req.post(GROQ_URL, json={
            "model": GROQ_MODEL, "messages": msgs, "max_tokens": 800, "temperature": 0.85
        }, headers={"Authorization": f"Bearer {GROQ_API_KEY}"}, timeout=30)
        data = resp.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        return f"[Ошибка ответа: {e}]"

def ensure_artgram_bot():
    bot = User.query.filter_by(username='ArtGram').first()
    if not bot:
        bot = User(
            username='ArtGram', display_name='ArtGramm',
            password_hash=hash_pw(os.urandom(16).hex()),
            bio='Официальный бот ArtGramm. Новости, обновления, поддержка.',
            is_bot=True, badge='official', avatar_color='#2AABEE',
            pinned=True, is_admin=False,
            bot_description='Я официальный бот мессенджера ArtGramm. Я информирую пользователей об обновлениях и новостях платформы.',
            bot_personality='Дружелюбный, профессиональный, всегда готов помочь.',
            bot_traits='["дружелюбный","профессиональный","информативный"]',
        )
        db.session.add(bot)
        db.session.commit()
    return bot

def ensure_admin():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin', display_name='Администратор',
            password_hash=hash_pw('admin123'),
            is_admin=True, badge='official', avatar_color='#E53935',
            bio='Администратор ArtGramm'
        )
        db.session.add(admin)
        db.session.commit()
    return admin

# ═══════════════════════════ ROUTES ═══════════════════════════

# ─── AUTH ───
@app.route('/api/auth/register', methods=['POST'])
def register():
    d = request.json
    username = (d.get('username') or '').strip().lower()
    display_name = (d.get('display_name') or '').strip()
    password = d.get('password', '')
    if not username or not display_name or not password:
        return jsonify({'error': 'Заполни все поля'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Юзернейм минимум 3 символа'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Юзернейм занят'}), 400
    colors = ['#2AABEE','#E53935','#43A047','#FB8C00','#8E24AA','#00ACC1','#D81B60','#3949AB']
    u = User(
        username=username, display_name=display_name,
        password_hash=hash_pw(password),
        avatar_color=colors[len(username) % len(colors)],
        phone=d.get('phone', '')
    )
    db.session.add(u)
    db.session.commit()
    # Start chat with ArtGram bot
    bot = ensure_artgram_bot()
    chat = get_or_create_private_chat(u.id, bot.id)
    welcome = Message(
        chat_id=chat.id, sender_id=bot.id,
        text=f"Добро пожаловать в ArtGramm, {display_name}! Я официальный бот платформы. Здесь ты можешь общаться с людьми и AI-ботами. Если есть вопросы — спрашивай!"
    )
    db.session.add(welcome)
    chat.last_message_text = welcome.text[:60]
    chat.last_message_time = datetime.utcnow()
    db.session.commit()
    session['user_id'] = u.id
    return jsonify({'user': user_to_dict(u, True)})

@app.route('/api/auth/login', methods=['POST'])
def login():
    d = request.json
    u = User.query.filter_by(username=d.get('username','').lower()).first()
    if not u or u.password_hash != hash_pw(d.get('password','')):
        return jsonify({'error': 'Неверный логин или пароль'}), 401
    if u.is_banned:
        return jsonify({'error': 'Аккаунт заблокирован'}), 403
    u.online = True
    u.last_seen = datetime.utcnow()
    db.session.commit()
    session['user_id'] = u.id
    return jsonify({'user': user_to_dict(u, True)})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    u = get_current_user()
    if u:
        u.online = False
        u.last_seen = datetime.utcnow()
        db.session.commit()
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me')
def me():
    u = get_current_user()
    if not u: return jsonify({'error': 'Не авторизован'}), 401
    return jsonify({'user': user_to_dict(u, True)})

# ─── USERS ───
@app.route('/api/users/search')
def search_users():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    q = request.args.get('q', '').lower().strip()
    if len(q) < 1: return jsonify([])
    users = User.query.filter(
        (User.username.ilike(f'%{q}%')) | (User.display_name.ilike(f'%{q}%')),
        User.is_banned == False
    ).limit(20).all()
    return jsonify([user_to_dict(x) for x in users])

@app.route('/api/users/<int:uid>')
def get_user(uid):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    target = User.query.get_or_404(uid)
    return jsonify(user_to_dict(target))

@app.route('/api/users/me', methods=['PUT'])
def update_me():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    if 'display_name' in d and d['display_name'].strip():
        u.display_name = d['display_name'].strip()
    if 'bio' in d: u.bio = d['bio']
    if 'avatar_b64' in d: u.avatar_b64 = d['avatar_b64']
    if 'avatar_color' in d: u.avatar_color = d['avatar_color']
    if 'phone' in d: u.phone = d['phone']
    if 'username' in d:
        new_u = d['username'].strip().lower()
        if new_u and new_u != u.username:
            if User.query.filter_by(username=new_u).first():
                return jsonify({'error': 'Юзернейм занят'}), 400
            u.username = new_u
    db.session.commit()
    return jsonify({'user': user_to_dict(u, True)})

@app.route('/api/users/top_bots')
def top_bots():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    bots = User.query.filter_by(is_bot=True, is_banned=False).order_by(User.bot_chat_count.desc()).limit(50).all()
    return jsonify([user_to_dict(b) for b in bots])

# ─── BOTS ───
@app.route('/api/bots/create', methods=['POST'])
def create_bot():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    username = (d.get('username') or '').strip().lower()
    display_name = (d.get('display_name') or '').strip()
    if not username or not display_name:
        return jsonify({'error': 'Нужен юзернейм и имя'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Юзернейм занят'}), 400
    colors = ['#2AABEE','#E53935','#43A047','#FB8C00','#8E24AA','#00ACC1','#D81B60','#9C27B0']
    import random
    bot = User(
        username=username, display_name=display_name,
        password_hash=hash_pw(os.urandom(16).hex()),
        is_bot=True, bot_owner_id=u.id,
        avatar_b64=d.get('avatar_b64', ''),
        avatar_color=random.choice(colors),
        bio=d.get('description', ''),
        bot_description=d.get('description', ''),
        bot_appearance=d.get('appearance', ''),
        bot_personality=d.get('personality', ''),
        bot_scenario=d.get('scenario', ''),
        bot_traits=json.dumps(d.get('traits', [])),
    )
    db.session.add(bot)
    db.session.commit()
    return jsonify({'bot': user_to_dict(bot)})

@app.route('/api/bots/<int:bot_id>/chat', methods=['POST'])
def chat_with_bot(bot_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    bot = User.query.filter_by(id=bot_id, is_bot=True).first()
    if not bot: return jsonify({'error': 'Бот не найден'}), 404
    d = request.json
    text = d.get('text', '').strip()
    if not text: return jsonify({'error': 'Пустое сообщение'}), 400
    # Get chat
    chat = get_or_create_private_chat(u.id, bot_id)
    # Save user message
    user_msg = Message(chat_id=chat.id, sender_id=u.id, text=text)
    db.session.add(user_msg)
    # Get bot conversation history
    conv = BotConversation.query.filter_by(user_id=u.id, bot_id=bot_id).first()
    if not conv:
        conv = BotConversation(user_id=u.id, bot_id=bot_id, history='[]')
        db.session.add(conv)
    history = json.loads(conv.history)
    # Get AI response
    bot_response = groq_chat(bot, history, text)
    # Update history
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": bot_response})
    if len(history) > 40: history = history[-40:]
    conv.history = json.dumps(history)
    conv.updated_at = datetime.utcnow()
    # Save bot message
    bot_msg = Message(chat_id=chat.id, sender_id=bot_id, text=bot_response)
    db.session.add(bot_msg)
    # Update chat
    chat.last_message_text = bot_response[:80]
    chat.last_message_time = datetime.utcnow()
    bot.bot_chat_count = (bot.bot_chat_count or 0) + 1
    # Update unread for user (bot's messages to user)
    member = ChatMember.query.filter_by(chat_id=chat.id, user_id=u.id).first()
    if member: member.unread_count = 0
    db.session.commit()
    # Emit via socket
    socketio.emit('new_message', msg_to_dict(user_msg), room=f'chat_{chat.id}')
    socketio.emit('new_message', msg_to_dict(bot_msg), room=f'chat_{chat.id}')
    return jsonify({'user_message': msg_to_dict(user_msg), 'bot_message': msg_to_dict(bot_msg)})

# ─── CHATS ───
@app.route('/api/chats')
def get_chats():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    members = ChatMember.query.filter_by(user_id=u.id).all()
    chat_ids = [m.chat_id for m in members]
    chats = Chat.query.filter(Chat.id.in_(chat_ids)).order_by(Chat.last_message_time.desc()).all()
    # Ensure ArtGram bot chat is first if pinned
    result = [chat_to_dict(c, u.id) for c in chats]
    result.sort(key=lambda x: (not x['pinned'], not x['is_pinned'], x['last_message_time'] or ''), reverse=False)
    result.sort(key=lambda x: (0 if x['pinned'] or x['is_pinned'] else 1))
    return jsonify(result)

@app.route('/api/chats/open/<int:target_id>', methods=['POST'])
def open_chat(target_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    target = User.query.get_or_404(target_id)
    chat = get_or_create_private_chat(u.id, target_id)
    return jsonify({'chat': chat_to_dict(chat, u.id)})

@app.route('/api/chats/<int:chat_id>')
def get_chat(chat_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    c = Chat.query.get_or_404(chat_id)
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=u.id).first()
    if not member: return jsonify({'error': 'Нет доступа'}), 403
    return jsonify(chat_to_dict(c, u.id))

@app.route('/api/chats/<int:chat_id>/messages')
def get_messages(chat_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=u.id).first()
    if not member: return jsonify({'error': 'Нет доступа'}), 403
    page = int(request.args.get('page', 1))
    per_page = 40
    msgs = Message.query.filter_by(chat_id=chat_id, deleted=False)\
        .order_by(Message.created_at.desc())\
        .offset((page-1)*per_page).limit(per_page).all()
    msgs.reverse()
    # Mark as read
    if member.unread_count > 0:
        member.unread_count = 0
        db.session.commit()
    return jsonify([msg_to_dict(m) for m in msgs])

@app.route('/api/chats/<int:chat_id>/send', methods=['POST'])
def send_message(chat_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=u.id).first()
    if not member: return jsonify({'error': 'Нет доступа'}), 403
    d = request.json
    text = d.get('text', '').strip()
    media_b64 = d.get('media_b64', '')
    media_type = d.get('media_type', '')
    file_name = d.get('file_name', '')
    reply_to = d.get('reply_to_id', 0)
    if not text and not media_b64:
        return jsonify({'error': 'Пустое сообщение'}), 400
    msg = Message(
        chat_id=chat_id, sender_id=u.id, text=text,
        media_b64=media_b64, media_type=media_type, file_name=file_name,
        reply_to_id=reply_to
    )
    db.session.add(msg)
    c = Chat.query.get(chat_id)
    c.last_message_text = text[:80] if text else f'[{media_type or "файл"}]'
    c.last_message_time = datetime.utcnow()
    # Increment unread for other members
    others = ChatMember.query.filter(ChatMember.chat_id==chat_id, ChatMember.user_id!=u.id).all()
    for om in others:
        if not om.is_muted:
            om.unread_count = (om.unread_count or 0) + 1
    db.session.commit()
    md = msg_to_dict(msg)
    socketio.emit('new_message', md, room=f'chat_{chat_id}')
    # If other party is a bot — trigger AI response
    if c.type == 'private':
        other_m = ChatMember.query.filter(ChatMember.chat_id==chat_id, ChatMember.user_id!=u.id).first()
        if other_m:
            bot = User.query.filter_by(id=other_m.user_id, is_bot=True).first()
            if bot and text:
                def respond():
                    with app.app_context():
                        conv = BotConversation.query.filter_by(user_id=u.id, bot_id=bot.id).first()
                        if not conv:
                            conv = BotConversation(user_id=u.id, bot_id=bot.id, history='[]')
                            db.session.add(conv)
                            db.session.flush()
                        history = json.loads(conv.history)
                        bot_response = groq_chat(bot, history, text)
                        history.append({"role": "user", "content": text})
                        history.append({"role": "assistant", "content": bot_response})
                        if len(history) > 40: history = history[-40:]
                        conv.history = json.dumps(history)
                        conv.updated_at = datetime.utcnow()
                        bot_msg = Message(chat_id=chat_id, sender_id=bot.id, text=bot_response)
                        db.session.add(bot_msg)
                        c2 = Chat.query.get(chat_id)
                        c2.last_message_text = bot_response[:80]
                        c2.last_message_time = datetime.utcnow()
                        bot.bot_chat_count = (bot.bot_chat_count or 0) + 1
                        db.session.commit()
                        socketio.emit('new_message', msg_to_dict(bot_msg), room=f'chat_{chat_id}')
                threading.Thread(target=respond, daemon=True).start()
    return jsonify(md)

@app.route('/api/chats/<int:chat_id>/messages/<int:msg_id>', methods=['PUT'])
def edit_message(chat_id, msg_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    msg = Message.query.filter_by(id=msg_id, chat_id=chat_id, sender_id=u.id).first()
    if not msg: return jsonify({'error': 'Не найдено'}), 404
    msg.text = request.json.get('text', msg.text)
    msg.edited = True
    db.session.commit()
    socketio.emit('message_edited', msg_to_dict(msg), room=f'chat_{chat_id}')
    return jsonify(msg_to_dict(msg))

@app.route('/api/chats/<int:chat_id>/messages/<int:msg_id>', methods=['DELETE'])
def delete_message(chat_id, msg_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    msg = Message.query.filter_by(id=msg_id, chat_id=chat_id).first()
    if not msg: return jsonify({'error': 'Не найдено'}), 404
    if msg.sender_id != u.id and not u.is_admin:
        return jsonify({'error': 'Нет прав'}), 403
    msg.deleted = True
    msg.text = 'Сообщение удалено'
    db.session.commit()
    socketio.emit('message_deleted', {'id': msg_id, 'chat_id': chat_id}, room=f'chat_{chat_id}')
    return jsonify({'ok': True})

@app.route('/api/chats/<int:chat_id>/messages/<int:msg_id>/react', methods=['POST'])
def react(chat_id, msg_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    msg = Message.query.get_or_404(msg_id)
    emoji = request.json.get('emoji', '')
    reactions = json.loads(msg.reactions or '{}')
    if emoji not in reactions: reactions[emoji] = []
    if u.id in reactions[emoji]: reactions[emoji].remove(u.id)
    else: reactions[emoji].append(u.id)
    if not reactions[emoji]: del reactions[emoji]
    msg.reactions = json.dumps(reactions)
    db.session.commit()
    socketio.emit('message_reaction', {'id': msg_id, 'chat_id': chat_id, 'reactions': reactions}, room=f'chat_{chat_id}')
    return jsonify({'reactions': reactions})

@app.route('/api/chats/<int:chat_id>/pin', methods=['POST'])
def pin_chat(chat_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=u.id).first()
    if not member: return jsonify({'error': 'Нет доступа'}), 403
    member.is_pinned = not member.is_pinned
    db.session.commit()
    return jsonify({'pinned': member.is_pinned})

@app.route('/api/chats/<int:chat_id>/mute', methods=['POST'])
def mute_chat(chat_id):
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    member = ChatMember.query.filter_by(chat_id=chat_id, user_id=u.id).first()
    if not member: return jsonify({'error': 'Нет доступа'}), 403
    member.is_muted = not member.is_muted
    db.session.commit()
    return jsonify({'muted': member.is_muted})

# ─── GROUPS ───
@app.route('/api/groups/create', methods=['POST'])
def create_group():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    name = (d.get('name') or '').strip()
    if not name: return jsonify({'error': 'Нужно название'}), 400
    g = Chat(
        type='group', name=name,
        avatar_b64=d.get('avatar_b64', ''),
        avatar_color=d.get('color', '#2AABEE'),
        description=d.get('description', ''),
        invite_link=str(uuid.uuid4())[:8],
        last_message_time=datetime.utcnow(),
        members_count=1
    )
    db.session.add(g)
    db.session.flush()
    db.session.add(ChatMember(chat_id=g.id, user_id=u.id, role='owner'))
    # Add members
    for mid in d.get('member_ids', []):
        if mid != u.id:
            m = User.query.get(mid)
            if m:
                db.session.add(ChatMember(chat_id=g.id, user_id=mid))
                g.members_count += 1
    # System message
    sys_msg = Message(chat_id=g.id, sender_id=u.id, text=f'{u.display_name} создал группу «{name}»')
    db.session.add(sys_msg)
    g.last_message_text = sys_msg.text[:80]
    db.session.commit()
    return jsonify({'chat': chat_to_dict(g, u.id)})

# ─── ADMIN ───
def require_admin():
    u = get_current_user()
    if not u or not u.is_admin:
        return None, jsonify({'error': 'Нет прав администратора'}), 403
    return u, None, None

@app.route('/api/admin/users')
def admin_users():
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    q = request.args.get('q', '').strip()
    page = int(request.args.get('page', 1))
    query = User.query
    if q:
        query = query.filter((User.username.ilike(f'%{q}%')) | (User.display_name.ilike(f'%{q}%')))
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=30)
    return jsonify({
        'users': [user_to_dict(x, True) for x in users.items],
        'total': users.total, 'pages': users.pages, 'page': page
    })

@app.route('/api/admin/users/<int:uid>', methods=['GET'])
def admin_get_user(uid):
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    target = User.query.get_or_404(uid)
    return jsonify(user_to_dict(target, True))

@app.route('/api/admin/users/<int:uid>', methods=['PUT'])
def admin_update_user(uid):
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    target = User.query.get_or_404(uid)
    d = request.json
    for field in ['display_name','bio','avatar_b64','avatar_color','badge','label_color','phone','username','is_admin','is_banned','two_fa']:
        if field in d:
            setattr(target, field, d[field])
    db.session.commit()
    return jsonify(user_to_dict(target, True))

@app.route('/api/admin/users/<int:uid>/ban', methods=['POST'])
def admin_ban(uid):
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    target = User.query.get_or_404(uid)
    target.is_banned = not target.is_banned
    db.session.commit()
    return jsonify({'banned': target.is_banned})

@app.route('/api/admin/users/<int:uid>/badge', methods=['POST'])
def admin_badge(uid):
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    target = User.query.get_or_404(uid)
    d = request.json
    target.badge = d.get('badge', '')
    target.label_color = d.get('label_color', '')
    db.session.commit()
    return jsonify(user_to_dict(target))

@app.route('/api/admin/users/<int:uid>/username', methods=['POST'])
def admin_set_username(uid):
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    target = User.query.get_or_404(uid)
    new_username = request.json.get('username', '').strip().lower()
    if not new_username: return jsonify({'error': 'Нужен юзернейм'}), 400
    existing = User.query.filter_by(username=new_username).first()
    if existing and existing.id != uid:
        return jsonify({'error': 'Юзернейм занят'}), 400
    target.username = new_username
    db.session.commit()
    return jsonify(user_to_dict(target))

@app.route('/api/admin/broadcast', methods=['POST'])
def admin_broadcast():
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    text = request.json.get('text', '').strip()
    if not text: return jsonify({'error': 'Нужен текст'}), 400
    artgram_bot = ensure_artgram_bot()
    all_users = User.query.filter_by(is_bot=False, is_banned=False).all()
    sent = 0
    for recipient in all_users:
        chat = get_or_create_private_chat(artgram_bot.id, recipient.id)
        msg = Message(chat_id=chat.id, sender_id=artgram_bot.id, text=text)
        db.session.add(msg)
        chat.last_message_text = text[:80]
        chat.last_message_time = datetime.utcnow()
        # Increment unread
        member = ChatMember.query.filter_by(chat_id=chat.id, user_id=recipient.id).first()
        if member: member.unread_count = (member.unread_count or 0) + 1
        sent += 1
    broadcast = Broadcast(admin_id=u.id, text=text, sent_count=sent)
    db.session.add(broadcast)
    db.session.commit()
    socketio.emit('broadcast', {'text': text, 'from': 'ArtGramm'})
    return jsonify({'ok': True, 'sent': sent})

@app.route('/api/admin/stats')
def admin_stats():
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    return jsonify({
        'total_users': User.query.filter_by(is_bot=False).count(),
        'total_bots': User.query.filter_by(is_bot=True).count(),
        'total_messages': Message.query.filter_by(deleted=False).count(),
        'total_chats': Chat.query.count(),
        'online_users': User.query.filter_by(online=True, is_bot=False).count(),
        'banned_users': User.query.filter_by(is_banned=True).count(),
        'broadcasts': Broadcast.query.count(),
        'reports': Report.query.filter_by(reviewed=False).count(),
    })

@app.route('/api/admin/broadcasts')
def admin_broadcasts():
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    bs = Broadcast.query.order_by(Broadcast.created_at.desc()).limit(50).all()
    return jsonify([{
        'id': b.id, 'text': b.text,
        'created_at': b.created_at.isoformat(),
        'sent_count': b.sent_count
    } for b in bs])

@app.route('/api/admin/reports')
def admin_reports():
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    reports = Report.query.order_by(Report.created_at.desc()).limit(100).all()
    result = []
    for r in reports:
        reporter = User.query.get(r.reporter_id)
        target = User.query.get(r.target_id)
        result.append({
            'id': r.id,
            'reporter': reporter.username if reporter else '?',
            'target': target.username if target else '?',
            'target_id': r.target_id,
            'reason': r.reason,
            'created_at': r.created_at.isoformat(),
            'reviewed': r.reviewed
        })
    return jsonify(result)

@app.route('/api/admin/reports/<int:rid>/review', methods=['POST'])
def review_report(rid):
    u = get_current_user()
    if not u or not u.is_admin: return jsonify({'error': 'Нет прав'}), 403
    r = Report.query.get_or_404(rid)
    r.reviewed = True
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/report', methods=['POST'])
def report_user():
    u = get_current_user()
    if not u: return jsonify({'error': 'Unauthorized'}), 401
    d = request.json
    r = Report(reporter_id=u.id, target_id=d.get('target_id'), reason=d.get('reason',''))
    db.session.add(r)
    db.session.commit()
    return jsonify({'ok': True})

# ─── SOCKET ───
@socketio.on('join')
def on_join(data):
    room = f"chat_{data.get('chat_id')}"
    join_room(room)

@socketio.on('leave')
def on_leave(data):
    room = f"chat_{data.get('chat_id')}"
    leave_room(room)

@socketio.on('typing')
def on_typing(data):
    u = get_current_user()
    if u:
        socketio.emit('typing', {'user_id': u.id, 'username': u.display_name, 'chat_id': data.get('chat_id')},
                     room=f"chat_{data.get('chat_id')}", include_self=False)

@socketio.on('connect')
def on_connect():
    u = get_current_user()
    if u:
        u.online = True
        u.last_seen = datetime.utcnow()
        db.session.commit()
        emit('connected', {'user_id': u.id})

@socketio.on('disconnect')
def on_disconnect():
    u = get_current_user()
    if u:
        u.online = False
        u.last_seen = datetime.utcnow()
        db.session.commit()

# ═══════════════════════════ MAIN HTML ═══════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>ArtGramm</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.6.1/socket.io.min.js"></script>
<style>
:root{--blue:#2AABEE;--dark-blue:#1a8fd1;--bg:#f0f2f5;--white:#fff;--text:#000;--sec:#8a8a8a;--div:#e4e4e4;--msg-out:#dcf8c6;--msg-in:#fff;--green:#4fae4e;--red:#e53935;--radius:12px}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;outline:none}
html,body{height:100%;width:100%;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);max-width:480px;margin:0 auto;position:relative}
.screen{position:absolute;inset:0;background:var(--bg);display:none;flex-direction:column;overflow:hidden}
.screen.active{display:flex}
.slide-in{animation:sIn .22s cubic-bezier(.4,0,.2,1)}
.slide-back{animation:sBack .22s cubic-bezier(.4,0,.2,1)}
@keyframes sIn{from{transform:translateX(100%)}to{transform:translateX(0)}}
@keyframes sBack{from{transform:translateX(-30%)}to{transform:translateX(0)}}
/* TOP BAR */
.tb{background:var(--white);display:flex;align-items:center;padding:8px 12px;padding-top:calc(8px + env(safe-area-inset-top,0px));border-bottom:1px solid var(--div);gap:10px;min-height:54px;flex-shrink:0;z-index:10;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.tb-title{font-size:17px;font-weight:600;flex:1;color:var(--text)}
.tb-sub{font-size:12px;color:var(--sec);margin-top:1px}
.tb-back{width:38px;height:38px;display:flex;align-items:center;justify-content:center;cursor:pointer;margin-left:-4px;border-radius:50%;flex-shrink:0}
.tb-back:active{background:rgba(0,0,0,.06)}
.tb-info{flex:1;min-width:0;cursor:pointer}
.tb-actions{display:flex;gap:2px}
.ib{width:38px;height:38px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%;flex-shrink:0}
.ib:active{background:rgba(0,0,0,.08)}
/* TABS */
.tabs{display:flex;background:var(--white);border-bottom:1px solid var(--div);flex-shrink:0}
.tab{flex:1;padding:9px 2px;text-align:center;font-size:11px;font-weight:500;color:var(--sec);cursor:pointer;position:relative;transition:color .15s;white-space:nowrap}
.tab.on{color:var(--blue)}
.tab.on::after{content:'';position:absolute;bottom:0;left:15%;right:15%;height:2px;background:var(--blue);border-radius:2px 2px 0 0}
/* AVATAR */
.av{width:50px;height:50px;border-radius:50%;flex-shrink:0;overflow:hidden;position:relative;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:18px;color:#fff}
.av img{width:100%;height:100%;object-fit:cover}
.av-sm{width:34px;height:34px;font-size:13px}
.av-lg{width:68px;height:68px;font-size:24px}
.online-dot{position:absolute;bottom:1px;right:1px;width:12px;height:12px;background:var(--green);border:2px solid var(--white);border-radius:50%}
/* BADGE */
.badge{display:inline-flex;align-items:center;gap:3px;font-size:11px;padding:1px 6px;border-radius:10px;font-weight:500}
.badge-official{background:#2AABEE;color:#fff}
.badge-verified{background:#2AABEE;color:#fff}
.badge-scam{background:#e53935;color:#fff}
.badge-fake{background:#ff6b35;color:#fff}
/* VERIFIED CHECKMARK - реальная белая галочка */
.vcheck{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;background:var(--blue);border-radius:50%;margin-left:3px;flex-shrink:0}
.vcheck svg{width:10px;height:10px}
/* CHAT LIST */
.cl{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch}
.ci{display:flex;align-items:center;padding:8px 12px;background:var(--white);border-bottom:.5px solid var(--div);gap:10px;cursor:pointer;transition:background .1s;position:relative}
.ci:active{background:#f5f5f5}
.ci-pinned{background:#fafafa}
.ci-body{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.ci-row{display:flex;align-items:center;gap:4px}
.ci-name{font-size:15px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.ci-time{font-size:12px;color:var(--sec);flex-shrink:0}
.ci-msg{font-size:13px;color:var(--sec);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.ci-meta{display:flex;align-items:center;gap:4px;flex-shrink:0}
.unread{background:var(--blue);color:#fff;font-size:11px;font-weight:600;min-width:20px;height:20px;border-radius:10px;display:flex;align-items:center;justify-content:center;padding:0 5px}
.unread-muted{background:var(--sec)}
.pin-icon{opacity:.5}
/* MSG AREA */
.msg-area{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:8px 8px;display:flex;flex-direction:column;gap:2px;background:#e5ddd5}
.msg-bg-pattern{background-color:#e5ddd5}
.msg-wrap{display:flex;align-items:flex-end;gap:6px;max-width:100%}
.msg-wrap.out{flex-direction:row-reverse}
.msg-bubble{max-width:75%;background:var(--msg-in);border-radius:var(--radius);padding:7px 10px 5px;position:relative;word-break:break-word}
.msg-bubble.out{background:var(--msg-out)}
.msg-sender{font-size:12px;font-weight:600;color:var(--blue);margin-bottom:3px}
.msg-text{font-size:14px;line-height:1.5;color:var(--text)}
.msg-meta{display:flex;align-items:center;justify-content:flex-end;gap:4px;margin-top:3px}
.msg-time{font-size:11px;color:rgba(0,0,0,.4)}
.msg-check{display:flex;align-items:center}
.msg-check svg{width:14px;height:14px;fill:var(--blue)}
.msg-img{max-width:100%;border-radius:8px;display:block}
.msg-reply{background:rgba(0,0,0,.05);border-left:3px solid var(--blue);border-radius:4px;padding:4px 8px;margin-bottom:5px;font-size:12px}
.msg-reply-name{font-weight:600;color:var(--blue)}
.msg-reactions{display:flex;flex-wrap:wrap;gap:3px;margin-top:4px}
.reaction-pill{background:rgba(0,0,0,.06);border-radius:10px;padding:2px 7px;font-size:13px;cursor:pointer;border:.5px solid transparent}
.reaction-pill.mine{background:rgba(42,171,238,.15);border-color:var(--blue)}
.msg-date-sep{text-align:center;font-size:12px;color:var(--sec);padding:8px 0}
.msg-date-sep span{background:rgba(255,255,255,.7);padding:3px 10px;border-radius:10px}
.typing-ind{display:flex;align-items:center;gap:8px;padding:6px 12px}
.typing-dots{display:flex;gap:3px;align-items:center}
.typing-dots span{width:7px;height:7px;background:var(--sec);border-radius:50%;animation:td 1.2s infinite}
.typing-dots span:nth-child(2){animation-delay:.2s}
.typing-dots span:nth-child(3){animation-delay:.4s}
@keyframes td{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-5px)}}
.pinned-msg-bar{background:var(--white);border-bottom:1px solid var(--div);padding:6px 12px;display:flex;align-items:center;gap:8px;cursor:pointer;flex-shrink:0}
.pinned-msg-bar .pm-text{font-size:13px;color:var(--sec);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
/* INPUT BAR */
.input-bar{background:var(--white);border-top:1px solid var(--div);padding:6px 8px;padding-bottom:calc(6px + env(safe-area-inset-bottom,0px));display:flex;align-items:flex-end;gap:6px;flex-shrink:0}
.input-bar textarea{flex:1;border:none;background:var(--bg);border-radius:20px;padding:9px 14px;font-size:15px;font-family:inherit;resize:none;max-height:120px;line-height:1.4;color:var(--text)}
.input-bar textarea::placeholder{color:var(--sec)}
.send-btn{width:42px;height:42px;background:var(--blue);border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;transition:transform .1s,background .1s}
.send-btn:active{transform:scale(.93);background:var(--dark-blue)}
.send-btn svg{width:22px;height:22px;fill:#fff}
.attach-btn{width:38px;height:38px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%}
.attach-btn:active{background:rgba(0,0,0,.06)}
.reply-bar{background:rgba(42,171,238,.08);border-top:1px solid var(--div);padding:6px 12px;display:flex;align-items:center;gap:8px;flex-shrink:0}
.reply-bar .rb-text{flex:1;font-size:13px;color:var(--text)}
.reply-bar .rb-cancel{width:28px;height:28px;display:flex;align-items:center;justify-content:center;cursor:pointer;border-radius:50%}
.reply-bar .rb-cancel:active{background:rgba(0,0,0,.08)}
/* PROFILE */
.profile-header{background:linear-gradient(135deg,var(--blue),#1a8fd1);padding:20px 16px 24px;display:flex;flex-direction:column;align-items:center;gap:10px;flex-shrink:0}
.profile-header .av-lg{border:3px solid rgba(255,255,255,.5)}
.profile-header h2{font-size:20px;font-weight:700;color:#fff}
.profile-header p{font-size:13px;color:rgba(255,255,255,.8)}
.profile-content{flex:1;overflow-y:auto;background:var(--bg);padding:12px}
.pcard{background:var(--white);border-radius:var(--radius);padding:14px 16px;margin-bottom:10px}
.pcard-label{font-size:12px;color:var(--sec);margin-bottom:4px}
.pcard-value{font-size:15px;color:var(--text)}
.pcard-row{display:flex;align-items:center;padding:11px 0;border-bottom:.5px solid var(--div);gap:10px;cursor:pointer}
.pcard-row:last-child{border-bottom:none}
.pcard-row:active{background:#f5f5f5;border-radius:8px;margin:0 -8px;padding:11px 8px}
.pcard-icon{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.pcard-icon.blue{background:rgba(42,171,238,.12)}
.pcard-icon.red{background:rgba(229,57,53,.12)}
.pcard-icon.green{background:rgba(79,174,78,.12)}
.pcard-icon.orange{background:rgba(255,107,53,.12)}
/* FORMS */
.form-wrap{flex:1;overflow-y:auto;padding:16px}
.form-section{background:var(--white);border-radius:var(--radius);margin-bottom:12px;overflow:hidden}
.form-section-title{font-size:13px;color:var(--blue);padding:12px 16px 4px;font-weight:500}
.form-row{display:flex;flex-direction:column;padding:10px 16px;border-bottom:.5px solid var(--div)}
.form-row:last-child{border-bottom:none}
.form-label{font-size:12px;color:var(--sec);margin-bottom:4px}
.form-input{font-size:15px;border:none;background:none;color:var(--text);font-family:inherit;width:100%}
.form-input::placeholder{color:var(--sec)}
.form-textarea{font-size:15px;border:none;background:none;color:var(--text);font-family:inherit;width:100%;resize:none;min-height:70px;line-height:1.5}
.form-textarea::placeholder{color:var(--sec)}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;border-radius:10px;cursor:pointer;font-size:15px;font-weight:500;padding:13px 16px;border:none;transition:opacity .15s}
.btn:active{opacity:.8}
.btn-blue{background:var(--blue);color:#fff}
.btn-red{background:var(--red);color:#fff}
.btn-outline{background:var(--white);color:var(--blue);border:1px solid var(--blue)}
.btn-gray{background:var(--div);color:var(--text)}
/* TRAITS */
.traits-grid{display:flex;flex-wrap:wrap;gap:7px;padding:10px 16px}
.trait-chip{padding:7px 13px;border-radius:20px;background:var(--bg);font-size:13px;cursor:pointer;border:1px solid var(--div);transition:all .15s;color:var(--text)}
.trait-chip.sel{background:var(--blue);color:#fff;border-color:var(--blue)}
/* BOT CARD */
.bot-card{background:var(--white);border-radius:var(--radius);padding:14px;margin-bottom:8px;display:flex;align-items:center;gap:12px;cursor:pointer}
.bot-card:active{background:#f8f8f8}
.bot-card-body{flex:1;min-width:0}
.bot-card-name{font-size:15px;font-weight:500;display:flex;align-items:center;gap:4px}
.bot-card-desc{font-size:13px;color:var(--sec);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bot-card-stats{font-size:12px;color:var(--sec);margin-top:3px}
/* MODAL / SHEET */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;display:none;align-items:flex-end}
.modal-overlay.show{display:flex}
.bottom-sheet{background:var(--white);border-radius:18px 18px 0 0;width:100%;max-height:85vh;overflow:hidden;display:flex;flex-direction:column;animation:sheetUp .25s cubic-bezier(.4,0,.2,1)}
@keyframes sheetUp{from{transform:translateY(100%)}to{transform:translateY(0)}}
.sheet-handle{width:36px;height:4px;background:var(--div);border-radius:2px;margin:10px auto 8px;flex-shrink:0}
.sheet-title{font-size:17px;font-weight:600;padding:4px 16px 12px;flex-shrink:0;text-align:center}
.sheet-content{overflow-y:auto;flex:1;padding:0 16px 20px}
/* CONTEXT MENU */
.ctx-menu{position:fixed;background:var(--white);border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.15);z-index:200;overflow:hidden;min-width:160px;animation:ctxIn .15s}
@keyframes ctxIn{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:scale(1)}}
.ctx-item{display:flex;align-items:center;gap:10px;padding:12px 16px;font-size:15px;cursor:pointer}
.ctx-item:active{background:var(--bg)}
.ctx-item.red{color:var(--red)}
/* SEARCH */
.search-bar{background:var(--white);padding:8px 12px;border-bottom:1px solid var(--div);flex-shrink:0}
.search-input{width:100%;background:var(--bg);border:none;border-radius:10px;padding:9px 14px;font-size:14px;font-family:inherit;color:var(--text)}
.search-input::placeholder{color:var(--sec)}
/* FAB */
.fab{position:absolute;bottom:20px;right:16px;width:56px;height:56px;background:var(--blue);border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 4px 16px rgba(42,171,238,.5);z-index:20}
.fab:active{transform:scale(.93)}
.fab svg{width:26px;height:26px;fill:#fff}
/* SETTINGS */
.settings-list{flex:1;overflow-y:auto}
.sl-section{background:var(--white);border-radius:var(--radius);margin:10px 12px 0;overflow:hidden}
.sl-item{display:flex;align-items:center;padding:13px 16px;border-bottom:.5px solid var(--div);gap:12px;cursor:pointer}
.sl-item:last-child{border-bottom:none}
.sl-item:active{background:#f5f5f5}
.sl-icon{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.sl-label{flex:1;font-size:15px;color:var(--text)}
.sl-value{font-size:14px;color:var(--sec)}
.sl-arrow{opacity:.4}
/* ADMIN */
.admin-card{background:var(--white);border-radius:var(--radius);margin-bottom:8px;overflow:hidden}
.admin-card-title{font-size:13px;font-weight:600;color:var(--sec);padding:10px 14px 6px;border-bottom:.5px solid var(--div)}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--div)}
.stat-cell{background:var(--white);padding:14px;text-align:center}
.stat-num{font-size:26px;font-weight:700;color:var(--text)}
.stat-lbl{font-size:12px;color:var(--sec);margin-top:2px}
/* TOGGLE */
.toggle{width:46px;height:26px;background:var(--div);border-radius:13px;position:relative;cursor:pointer;transition:background .2s;flex-shrink:0}
.toggle.on{background:var(--blue)}
.toggle::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;background:var(--white);border-radius:50%;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.toggle.on::after{transform:translateX(20px)}
/* SCROLLBAR */
::-webkit-scrollbar{width:0;height:0}
/* EMPTY STATE */
.empty-state{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:32px;color:var(--sec);text-align:center}
.empty-state svg{width:64px;height:64px;opacity:.3}
.empty-state h3{font-size:17px;font-weight:500;color:var(--text)}
.empty-state p{font-size:14px;line-height:1.5}
/* AUTH */
.auth-screen{background:linear-gradient(160deg,#2AABEE 0%,#007dbf 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px;gap:20px}
.auth-logo{width:80px;height:80px;background:rgba(255,255,255,.2);border-radius:50%;display:flex;align-items:center;justify-content:center}
.auth-logo svg{width:44px;height:44px;fill:#fff}
.auth-title{font-size:24px;font-weight:700;color:#fff;text-align:center}
.auth-sub{font-size:14px;color:rgba(255,255,255,.8);text-align:center}
.auth-card{background:var(--white);border-radius:16px;padding:20px;width:100%;display:flex;flex-direction:column;gap:14px}
.auth-input{border:1.5px solid var(--div);border-radius:10px;padding:13px 14px;font-size:15px;font-family:inherit;color:var(--text);width:100%;transition:border-color .2s}
.auth-input:focus{border-color:var(--blue)}
.auth-switch{text-align:center;font-size:14px;color:rgba(255,255,255,.9);cursor:pointer}
.auth-switch span{text-decoration:underline}
/* NOTIFICATION */
.notif{position:fixed;top:calc(10px + env(safe-area-inset-top,0px));left:50%;transform:translateX(-50%);background:#333;color:#fff;padding:10px 18px;border-radius:20px;font-size:14px;z-index:999;animation:notifIn .3s;white-space:nowrap;max-width:90%}
@keyframes notifIn{from{opacity:0;transform:translateX(-50%) translateY(-20px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}
.notif.success{background:var(--green)}
.notif.error{background:var(--red)}
/* IMAGE PREVIEW */
.img-preview-overlay{position:fixed;inset:0;background:#000;z-index:300;display:none;flex-direction:column;align-items:center;justify-content:center}
.img-preview-overlay.show{display:flex}
.img-preview-overlay img{max-width:100%;max-height:90vh;object-fit:contain}
</style>
</head>
<body>

<!-- ══ AUTH ══ -->
<div id="s-auth" class="screen active auth-screen">
  <div class="auth-logo">
    <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8l-1.68 7.92c-.12.56-.44.7-.9.44l-2.46-1.82-1.18 1.14c-.14.14-.26.26-.52.26l.18-2.6 4.72-4.26c.2-.18-.04-.28-.32-.1L7.44 14.8l-2.4-.74c-.52-.16-.54-.52.12-.78l9.38-3.62c.44-.16.82.1.68.78l-.58-.64z"/></svg>
  </div>
  <div class="auth-title">ArtGramm</div>
  <div class="auth-sub">Мессенджер нового поколения</div>
  <div class="auth-card" id="auth-login-card">
    <div style="font-size:17px;font-weight:600;text-align:center">Войти</div>
    <input class="auth-input" id="auth-username" placeholder="Юзернейм" autocomplete="username">
    <input class="auth-input" id="auth-password" type="password" placeholder="Пароль" autocomplete="current-password">
    <button class="btn btn-blue" onclick="doLogin()">Войти</button>
  </div>
  <div class="auth-switch" onclick="toggleAuth()">Нет аккаунта? <span>Зарегистрироваться</span></div>
</div>

<!-- ══ REGISTER SHEET ══ -->
<div id="s-register" class="screen auth-screen" style="display:none">
  <div class="auth-logo"><svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8l-1.68 7.92c-.12.56-.44.7-.9.44l-2.46-1.82-1.18 1.14c-.14.14-.26.26-.52.26l.18-2.6 4.72-4.26c.2-.18-.04-.28-.32-.1L7.44 14.8l-2.4-.74c-.52-.16-.54-.52.12-.78l9.38-3.62c.44-.16.82.1.68.78l-.58-.64z"/></svg></div>
  <div class="auth-title">ArtGramm</div>
  <div class="auth-card">
    <div style="font-size:17px;font-weight:600;text-align:center">Регистрация</div>
    <input class="auth-input" id="reg-name" placeholder="Имя (отображаемое)" autocomplete="name">
    <input class="auth-input" id="reg-username" placeholder="Юзернейм (только латиница)" autocomplete="username">
    <input class="auth-input" id="reg-phone" placeholder="Телефон (необязательно)" type="tel">
    <input class="auth-input" id="reg-password" type="password" placeholder="Пароль" autocomplete="new-password">
    <button class="btn btn-blue" onclick="doRegister()">Создать аккаунт</button>
  </div>
  <div class="auth-switch" onclick="toggleAuth()">Уже есть аккаунт? <span>Войти</span></div>
</div>

<!-- ══ MAIN (CHAT LIST) ══ -->
<div id="s-main" class="screen">
  <div class="tb">
    <div class="tb-title">ArtGramm</div>
    <div class="tb-actions">
      <div class="ib" onclick="showSearch()">
        <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27A6.5 6.5 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16a6.5 6.5 0 0 0 4.23-1.57l.27.28v.79l5 4.99L20.49 19zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14" fill="var(--blue)"/></svg>
      </div>
      <div class="ib" onclick="showNewMenu()">
        <svg viewBox="0 0 24 24"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z" fill="var(--blue)"/></svg>
      </div>
      <div class="ib" onclick="goSettings()">
        <svg viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z" fill="var(--blue)"/></svg>
      </div>
    </div>
  </div>
  <div class="tabs">
    <div class="tab on" data-tab="all" onclick="switchTab('all',this)">Все</div>
    <div class="tab" data-tab="personal" onclick="switchTab('personal',this)">Личные</div>
    <div class="tab" data-tab="bots" onclick="switchTab('bots',this)">Боты</div>
    <div class="tab" data-tab="top" onclick="switchTab('top',this)">Топы</div>
  </div>
  <div class="cl" id="chat-list"></div>
</div>

<!-- ══ SEARCH ══ -->
<div id="s-search" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Поиск</div>
  </div>
  <div class="search-bar">
    <input class="search-input" id="search-input" placeholder="Найти пользователя или бота..." oninput="doSearch(this.value)" autocomplete="off">
  </div>
  <div class="cl" id="search-results" style="background:var(--white)">
    <div class="empty-state">
      <svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27A6.5 6.5 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16a6.5 6.5 0 0 0 4.23-1.57l.27.28v.79l5 4.99L20.49 19z"/></svg>
      <h3>Найди людей и ботов</h3>
      <p>Введи имя или @юзернейм</p>
    </div>
  </div>
</div>

<!-- ══ CHAT ══ -->
<div id="s-chat" class="screen">
  <div class="tb" id="chat-tb">
    <div class="tb-back" onclick="closeChat()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="av av-sm" id="chat-tb-av" onclick="openChatProfile()"></div>
    <div class="tb-info" onclick="openChatProfile()">
      <div class="tb-title" style="font-size:15px" id="chat-tb-name"></div>
      <div class="tb-sub" id="chat-tb-sub"></div>
    </div>
    <div class="tb-actions">
      <div class="ib" onclick="chatCall()">
        <svg viewBox="0 0 24 24"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z" fill="var(--blue)"/></svg>
      </div>
      <div class="ib" onclick="chatMenu()">
        <svg viewBox="0 0 24 24"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" fill="var(--blue)"/></svg>
      </div>
    </div>
  </div>
  <div id="pinned-msg-bar" class="pinned-msg-bar" style="display:none">
    <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:var(--blue);flex-shrink:0"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>
    <div class="pm-text" id="pinned-msg-text"></div>
    <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:var(--sec);flex-shrink:0" onclick="closePinnedBar()"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
  </div>
  <div class="msg-area" id="msg-area"></div>
  <div id="typing-bar" style="display:none" class="typing-ind">
    <div class="typing-dots"><span></span><span></span><span></span></div>
    <span style="font-size:13px;color:var(--sec)" id="typing-text"></span>
  </div>
  <div id="reply-bar" class="reply-bar" style="display:none">
    <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--blue);flex-shrink:0"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/></svg>
    <div class="rb-text" id="reply-preview"></div>
    <div class="rb-cancel" onclick="cancelReply()">
      <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--sec)"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
    </div>
  </div>
  <div class="input-bar">
    <div class="attach-btn" onclick="triggerAttach()">
      <svg viewBox="0 0 24 24" style="width:24px;height:24px;fill:var(--sec)"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
    </div>
    <input type="file" id="file-input" style="display:none" accept="image/*" onchange="handleFile(this)">
    <textarea id="msg-input" placeholder="Сообщение..." rows="1" oninput="autoResize(this);onTyping()" onkeydown="msgKeydown(event)"></textarea>
    <div class="send-btn" onclick="sendMsg()">
      <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </div>
  </div>
</div>

<!-- ══ CREATE BOT ══ -->
<div id="s-create-bot" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Создать бота</div>
  </div>
  <div class="form-wrap" id="create-bot-form">
    <!-- Avatar -->
    <div style="display:flex;flex-direction:column;align-items:center;gap:10px;padding:16px 0 8px">
      <div class="av av-lg" id="bot-av-preview" style="background:#2AABEE;cursor:pointer" onclick="triggerBotAvatar()">
        <svg viewBox="0 0 24 24" style="width:30px;height:30px;fill:rgba(255,255,255,.7)"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>
      </div>
      <input type="file" id="bot-av-input" style="display:none" accept="image/*" onchange="setBotAvatar(this)">
      <div style="font-size:13px;color:var(--blue);cursor:pointer" onclick="triggerBotAvatar()">Загрузить аватарку</div>
    </div>
    <div class="form-section">
      <div class="form-section-title">Основное</div>
      <div class="form-row"><div class="form-label">Имя бота</div><input class="form-input" id="bot-name" placeholder="Например: Мия"></div>
      <div class="form-row"><div class="form-label">@юзернейм</div><input class="form-input" id="bot-username" placeholder="miya_bot"></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">Описание</div>
      <div class="form-row"><div class="form-label">Общее описание</div><textarea class="form-textarea" id="bot-desc" placeholder="Кто такой этот бот, чем занимается..."></textarea></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">Внешность</div>
      <div class="form-row"><textarea class="form-textarea" id="bot-appearance" placeholder="Опишите внешность: рост, цвет волос, стиль одежды..."></textarea></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">Характер и личность</div>
      <div class="form-row"><textarea class="form-textarea" id="bot-personality" placeholder="Характер, манера общения, привычки, ценности..."></textarea></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">Сценарий и обстановка</div>
      <div class="form-row"><textarea class="form-textarea" id="bot-scenario" placeholder="Где находитесь, что происходит, контекст встречи..."></textarea></div>
    </div>
    <div class="form-section">
      <div class="form-section-title">Качества характера (по желанию)</div>
      <div class="traits-grid" id="traits-grid"></div>
    </div>
    <div style="padding:16px 0">
      <button class="btn btn-blue" onclick="submitCreateBot()" style="width:100%">Создать бота</button>
    </div>
  </div>
</div>

<!-- ══ BOT PROFILE / USER PROFILE ══ -->
<div id="s-profile" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Профиль</div>
    <div class="tb-actions">
      <div class="ib" id="profile-more-btn" onclick="profileMore()">
        <svg viewBox="0 0 24 24"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" fill="var(--blue)"/></svg>
      </div>
    </div>
  </div>
  <div id="profile-content" style="flex:1;overflow-y:auto"></div>
</div>

<!-- ══ TOP BOTS ══ -->
<div id="s-top" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Топ ботов</div>
  </div>
  <div class="cl" id="top-bots-list"></div>
</div>

<!-- ══ SETTINGS ══ -->
<div id="s-settings" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Настройки</div>
  </div>
  <div id="settings-profile-header" class="profile-header" style="cursor:pointer" onclick="goEditProfile()"></div>
  <div class="settings-list">
    <div class="sl-section">
      <div class="sl-item" onclick="goEditProfile()">
        <div class="sl-icon blue"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--blue)"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg></div>
        <div class="sl-label">Редактировать профиль</div>
        <svg class="sl-arrow" viewBox="0 0 24 24" style="width:18px;height:18px;fill:#999"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
      </div>
      <div class="sl-item">
        <div class="sl-icon blue"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--blue)"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg></div>
        <div class="sl-label">Приватность</div>
        <svg class="sl-arrow" viewBox="0 0 24 24" style="width:18px;height:18px;fill:#999"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
      </div>
      <div class="sl-item">
        <div class="sl-icon blue"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--blue)"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg></div>
        <div class="sl-label">Уведомления</div>
        <svg class="sl-arrow" viewBox="0 0 24 24" style="width:18px;height:18px;fill:#999"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
      </div>
    </div>
    <div class="sl-section" style="margin-top:10px">
      <div class="sl-item" id="admin-panel-btn" onclick="goAdmin()" style="display:none">
        <div class="sl-icon red"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--red)"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/></svg></div>
        <div class="sl-label" style="color:var(--red)">Панель администратора</div>
        <svg class="sl-arrow" viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--red)"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
      </div>
      <div class="sl-item" onclick="doLogout()">
        <div class="sl-icon red"><svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--red)"><path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/></svg></div>
        <div class="sl-label" style="color:var(--red)">Выйти</div>
      </div>
    </div>
  </div>
</div>

<!-- ══ EDIT PROFILE ══ -->
<div id="s-edit-profile" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Редактировать профиль</div>
    <div class="ib" onclick="saveProfile()">
      <svg viewBox="0 0 24 24" style="width:22px;height:22px;fill:var(--blue)"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
    </div>
  </div>
  <div class="form-wrap">
    <div style="display:flex;flex-direction:column;align-items:center;gap:10px;padding:8px 0 16px">
      <div class="av av-lg" id="edit-av-preview" style="cursor:pointer" onclick="document.getElementById('edit-av-input').click()"></div>
      <input type="file" id="edit-av-input" style="display:none" accept="image/*" onchange="setEditAvatar(this)">
      <div style="font-size:13px;color:var(--blue);cursor:pointer" onclick="document.getElementById('edit-av-input').click()">Изменить фото</div>
    </div>
    <div class="form-section">
      <div class="form-row"><div class="form-label">Имя</div><input class="form-input" id="edit-name" placeholder="Имя"></div>
      <div class="form-row"><div class="form-label">@юзернейм</div><input class="form-input" id="edit-username" placeholder="username"></div>
      <div class="form-row"><div class="form-label">Биография</div><textarea class="form-textarea" id="edit-bio" placeholder="Расскажи о себе..."></textarea></div>
      <div class="form-row"><div class="form-label">Телефон</div><input class="form-input" id="edit-phone" type="tel" placeholder="+7..."></div>
    </div>
  </div>
</div>

<!-- ══ ADMIN PANEL ══ -->
<div id="s-admin" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title" style="color:var(--red)">Админ панель</div>
  </div>
  <div class="tabs">
    <div class="tab on" onclick="adminTab('stats',this)">Статы</div>
    <div class="tab" onclick="adminTab('users',this)">Юзеры</div>
    <div class="tab" onclick="adminTab('broadcast',this)">Рассылка</div>
    <div class="tab" onclick="adminTab('reports',this)">Жалобы</div>
  </div>
  <div style="flex:1;overflow-y:auto" id="admin-content"></div>
</div>

<!-- ══ ADMIN USER EDIT ══ -->
<div id="s-admin-edit" class="screen">
  <div class="tb">
    <div class="tb-back" onclick="goBack()">
      <svg viewBox="0 0 24 24"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" fill="var(--blue)"/></svg>
    </div>
    <div class="tb-title">Управление пользователем</div>
  </div>
  <div id="admin-user-content" style="flex:1;overflow-y:auto"></div>
</div>

<!-- ══ NEW MENU MODAL ══ -->
<div class="modal-overlay" id="new-menu-modal" onclick="closeModal('new-menu-modal')">
  <div class="bottom-sheet" onclick="event.stopPropagation()">
    <div class="sheet-handle"></div>
    <div class="sheet-title">Создать</div>
    <div class="sheet-content">
      <div class="pcard">
        <div class="pcard-row" onclick="closeModal('new-menu-modal');goScreen('s-create-bot')">
          <div class="pcard-icon blue">
            <svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:var(--blue)"><path d="M20 9V7c0-1.1-.9-2-2-2h-3c0-1.66-1.34-3-3-3S9 3.34 9 5H6c-1.1 0-2 .9-2 2v2c-1.66 0-3 1.34-3 3s1.34 3 3 3v4c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-4c1.66 0 3-1.34 3-3s-1.34-3-3-3zM7 17V7h10v10H7zm-1-6v-1h1v1H6zm4 0v-1h1v1h-1zm4 0v-1h1v1h-1z"/></svg>
          </div>
          <div style="flex:1"><div style="font-size:15px;font-weight:500">Создать бота</div><div style="font-size:13px;color:var(--sec)">AI-персонаж на Groq</div></div>
          <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--sec)"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
        </div>
        <div class="pcard-row" onclick="closeModal('new-menu-modal');openNewChat()">
          <div class="pcard-icon blue">
            <svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:var(--blue)"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
          </div>
          <div style="flex:1"><div style="font-size:15px;font-weight:500">Новый чат</div><div style="font-size:13px;color:var(--sec)">Начать переписку</div></div>
          <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--sec)"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
        </div>
        <div class="pcard-row" onclick="closeModal('new-menu-modal');openNewGroup()">
          <div class="pcard-icon green">
            <svg viewBox="0 0 24 24" style="width:20px;height:20px;fill:var(--green)"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/></svg>
          </div>
          <div style="flex:1"><div style="font-size:15px;font-weight:500">Создать группу</div><div style="font-size:13px;color:var(--sec)">Групповой чат</div></div>
          <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--sec)"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ══ NEW CHAT SEARCH MODAL ══ -->
<div class="modal-overlay" id="new-chat-modal" onclick="closeModal('new-chat-modal')">
  <div class="bottom-sheet" onclick="event.stopPropagation()" style="max-height:90vh">
    <div class="sheet-handle"></div>
    <div class="sheet-title">Новый чат</div>
    <div style="padding:0 16px 12px">
      <input class="search-input" id="new-chat-search" placeholder="Поиск..." oninput="newChatSearch(this.value)" autocomplete="off">
    </div>
    <div style="overflow-y:auto;flex:1;max-height:60vh" id="new-chat-results"></div>
  </div>
</div>

<!-- ══ CONTEXT MENU ══ -->
<div id="ctx-menu" class="ctx-menu" style="display:none"></div>

<!-- ══ IMG PREVIEW ══ -->
<div class="img-preview-overlay" id="img-preview" onclick="closeImgPreview()">
  <img id="img-preview-img" src="">
  <div style="color:#fff;font-size:13px;padding:10px;opacity:.7">Нажми чтобы закрыть</div>
</div>

<script>
// ═══════════════════ STATE ═══════════════════
let me = null;
let currentChatId = null;
let currentChatData = null;
let screenStack = ['s-main'];
let replyTo = null;
let typingTimer = null;
let lastMsgDate = null;
let socket = null;
let allChats = [];
let currentTab = 'all';
let adminUserId = null;
let editAvatarB64 = '';
let botAvatarB64 = '';
let selectedTraits = [];
let searchTimer = null;

const TRAITS = [
  'добрый','злой','умный','наивный','загадочный','весёлый','серьёзный','романтичный',
  'холодный','страстный','дерзкий','нежный','мудрый','импульсивный','спокойный',
  'агрессивный','застенчивый','уверенный','ироничный','саркастичный','харизматичный',
  'интроверт','экстраверт','честный','лживый','верный','ревнивый','свободолюбивый',
  'заботливый','эгоистичный','смелый','трусливый','упрямый','гибкий','творческий',
  'практичный','мечтательный','циничный','оптимистичный','пессимистичный','загадочный',
  'открытый','скрытный','чувствительный','бесстрастный','игривый','строгий',
  'философский','спортивный','ленивый','трудолюбивый','преданный','независимый',
  'манипулятивный','искренний','грубый','вежливый','таинственный','живой',
];

// ═══════════════════ INIT ═══════════════════
window.onload = () => {
  initTraits();
  checkAuth();
};

function initTraits() {
  const g = document.getElementById('traits-grid');
  TRAITS.forEach(t => {
    const chip = document.createElement('div');
    chip.className = 'trait-chip';
    chip.textContent = t;
    chip.onclick = () => {
      if (selectedTraits.includes(t)) {
        selectedTraits = selectedTraits.filter(x => x !== t);
        chip.classList.remove('sel');
      } else {
        selectedTraits.push(t);
        chip.classList.add('sel');
      }
    };
    g.appendChild(chip);
  });
}

async function checkAuth() {
  try {
    const r = await api('/api/auth/me');
    me = r.user;
    onLogin();
  } catch { showScreen('s-auth'); }
}

function onLogin() {
  showScreen('s-main');
  initSocket();
  loadChats();
  updateSettingsHeader();
  if (me && me.is_admin) document.getElementById('admin-panel-btn').style.display = 'flex';
}

// ═══════════════════ API ═══════════════════
async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: {'Content-Type': 'application/json'},
    credentials: 'include',
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const d = await res.json();
  if (!res.ok) throw new Error(d.error || 'Ошибка');
  return d;
}

// ═══════════════════ SOCKET ═══════════════════
function initSocket() {
  socket = io();
  socket.on('new_message', (msg) => {
    if (msg.chat_id == currentChatId) appendMessage(msg);
    updateChatInList(msg.chat_id, msg.text || '[медиа]', msg.created_at);
    if (msg.sender_id !== me?.id) incrementUnread(msg.chat_id);
  });
  socket.on('message_edited', (msg) => {
    if (msg.chat_id == currentChatId) {
      const el = document.querySelector(`[data-msg-id="${msg.id}"] .msg-text`);
      if (el) { el.textContent = msg.text; }
    }
  });
  socket.on('message_deleted', (d) => {
    if (d.chat_id == currentChatId) {
      const el = document.querySelector(`[data-msg-id="${d.id}"] .msg-text`);
      if (el) { el.textContent = 'Сообщение удалено'; el.style.fontStyle = 'italic'; el.style.color = 'var(--sec)'; }
    }
  });
  socket.on('typing', (d) => {
    if (d.chat_id == currentChatId && d.user_id !== me?.id) showTyping(d.username);
  });
  socket.on('message_reaction', (d) => {
    if (d.chat_id == currentChatId) updateReactions(d.id, d.reactions);
  });
  socket.on('broadcast', (d) => {
    notify(`ArtGramm: ${d.text}`, 'success');
    loadChats();
  });
}

// ═══════════════════ SCREENS ═══════════════════
function showScreen(id, anim = true) {
  document.querySelectorAll('.screen').forEach(s => {
    s.classList.remove('active','slide-in','slide-back');
  });
  const el = document.getElementById(id);
  el.classList.add('active');
  if (anim && id !== 's-auth') el.classList.add('slide-in');
  if (!screenStack.includes(id) || screenStack[screenStack.length-1] !== id) {
    screenStack.push(id);
  }
}

function goBack() {
  if (screenStack.length > 1) {
    screenStack.pop();
    const prev = screenStack[screenStack.length-1];
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active','slide-in','slide-back'));
    const el = document.getElementById(prev);
    el.classList.add('active','slide-back');
  }
}

function goScreen(id) { showScreen(id); }

// ═══════════════════ AUTH ═══════════════════
function toggleAuth() {
  const login = document.getElementById('s-auth');
  const reg = document.getElementById('s-register');
  if (login.style.display !== 'none' && login.classList.contains('active')) {
    login.classList.remove('active');
    reg.classList.add('active');
    reg.style.display = '';
  } else {
    reg.classList.remove('active');
    login.classList.add('active');
    login.style.display = '';
  }
}

async function doLogin() {
  const username = document.getElementById('auth-username').value.trim();
  const password = document.getElementById('auth-password').value;
  if (!username || !password) { notify('Заполни все поля', 'error'); return; }
  try {
    const r = await api('/api/auth/login', {method:'POST', body:{username, password}});
    me = r.user;
    onLogin();
  } catch(e) { notify(e.message, 'error'); }
}

async function doRegister() {
  const display_name = document.getElementById('reg-name').value.trim();
  const username = document.getElementById('reg-username').value.trim();
  const phone = document.getElementById('reg-phone').value.trim();
  const password = document.getElementById('reg-password').value;
  if (!display_name || !username || !password) { notify('Заполни все поля', 'error'); return; }
  try {
    const r = await api('/api/auth/register', {method:'POST', body:{display_name, username, phone, password}});
    me = r.user;
    onLogin();
  } catch(e) { notify(e.message, 'error'); }
}

async function doLogout() {
  await api('/api/auth/logout', {method:'POST'});
  me = null; currentChatId = null;
  screenStack = ['s-auth'];
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  document.getElementById('s-auth').classList.add('active');
}

// ═══════════════════ CHAT LIST ═══════════════════
async function loadChats() {
  try {
    allChats = await api('/api/chats');
    renderChats();
  } catch(e) { console.error(e); }
}

function renderChats() {
  const el = document.getElementById('chat-list');
  let chats = allChats;
  if (currentTab === 'personal') chats = chats.filter(c => !c.is_bot && c.type === 'private');
  else if (currentTab === 'bots') chats = chats.filter(c => c.is_bot);
  else if (currentTab === 'top') { loadTopBots(); return; }

  if (!chats.length) {
    el.innerHTML = `<div class="empty-state">
      <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
      <h3>Нет чатов</h3><p>Найди людей или создай бота</p></div>`;
    return;
  }
  el.innerHTML = chats.map(c => chatItemHTML(c)).join('');
}

function chatItemHTML(c) {
  const av = avatarHTML(c.name, c.avatar_b64, c.avatar_color, 50);
  const time = formatTime(c.last_message_time);
  const unread = c.unread_count > 0 ? `<div class="unread${c.is_muted?' unread-muted':''}">${c.unread_count > 99 ? '99+' : c.unread_count}</div>` : '';
  const pin = c.is_pinned || c.pinned ? `<svg class="pin-icon" viewBox="0 0 24 24" style="width:14px;height:14px;fill:var(--sec)"><path d="M16 12V4h1V2H7v2h1v8l-2 2v2h5.2v6h1.6v-6H18v-2l-2-2z"/></svg>` : '';
  const badge = badgeHTML(c.badge);
  const msg_preview = c.last_message_text ? escHtml(c.last_message_text).substring(0, 60) : 'Нет сообщений';
  return `<div class="ci${c.is_pinned||c.pinned?' ci-pinned':''}" onclick="openChat(${c.id})">
    ${av}
    <div class="ci-body">
      <div class="ci-row">
        <div class="ci-name">${escHtml(c.name)}${badge}${c.is_bot && c.badge==='official' ? verifiedCheck() : ''}</div>
        <div class="ci-time">${time}</div>
      </div>
      <div class="ci-row">
        <div class="ci-msg">${msg_preview}</div>
        <div class="ci-meta">${pin}${unread}</div>
      </div>
    </div>
  </div>`;
}

function switchTab(tab, el) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('on'));
  el.classList.add('on');
  if (tab === 'top') showTopBots();
  else renderChats();
}

function showTopBots() {
  const el = document.getElementById('chat-list');
  el.innerHTML = '<div style="padding:16px;text-align:center;color:var(--sec);font-size:14px">Загрузка топ ботов...</div>';
  api('/api/users/top_bots').then(bots => {
    if (!bots.length) { el.innerHTML = `<div class="empty-state"><svg viewBox="0 0 24 24"><path d="M20 9V7c0-1.1-.9-2-2-2h-3c0-1.66-1.34-3-3-3S9 3.34 9 5H6c-1.1 0-2 .9-2 2v2c-1.66 0-3 1.34-3 3s1.34 3 3 3v4c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-4c1.66 0 3-1.34 3-3s-1.34-3-3-3z"/></svg><h3>Ботов пока нет</h3><p>Создай первого бота</p></div>`; return; }
    el.innerHTML = `<div style="padding:12px">` + bots.map((b, i) => `
      <div class="bot-card" onclick="openUserProfile(${b.id})">
        ${avatarHTML(b.display_name, b.avatar_b64, b.avatar_color, 46)}
        <div class="bot-card-body">
          <div class="bot-card-name">${i<3?['🥇','🥈','🥉'][i]+' ':''}${escHtml(b.display_name)}${b.badge==='official'?verifiedCheck():''}</div>
          <div class="bot-card-desc">@${b.username}</div>
          <div class="bot-card-stats">${b.bot_chat_count || 0} диалогов</div>
        </div>
      </div>`).join('') + `</div>`;
  });
}

function updateChatInList(chatId, text, time) {
  allChats = allChats.map(c => c.id === chatId ? {...c, last_message_text: text, last_message_time: time} : c);
  allChats.sort((a, b) => {
    if (a.pinned || a.is_pinned) return -1;
    if (b.pinned || b.is_pinned) return 1;
    return new Date(b.last_message_time) - new Date(a.last_message_time);
  });
  renderChats();
}

function incrementUnread(chatId) {
  allChats = allChats.map(c => c.id === chatId && c.id !== currentChatId ? {...c, unread_count: (c.unread_count||0)+1} : c);
  renderChats();
}

// ═══════════════════ OPEN CHAT ═══════════════════
async function openChat(chatId) {
  currentChatId = chatId;
  showScreen('s-chat');
  socket?.emit('join', {chat_id: chatId});
  // Load chat info
  const c = allChats.find(x => x.id === chatId) || await api(`/api/chats/${chatId}`);
  currentChatData = c;
  // Set topbar
  const nameEl = document.getElementById('chat-tb-name');
  const subEl = document.getElementById('chat-tb-sub');
  const avEl = document.getElementById('chat-tb-av');
  nameEl.innerHTML = escHtml(c.name) + (c.badge === 'official' ? verifiedCheck() : '') + badgeHTML(c.badge);
  avEl.style.background = c.avatar_color;
  if (c.avatar_b64) { avEl.innerHTML = `<img src="${c.avatar_b64}" style="width:100%;height:100%;border-radius:50%;object-fit:cover">`; }
  else { avEl.innerHTML = `<div class="av-sm" style="width:100%;height:100%;background:${c.avatar_color};display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:14px">${getInitials(c.name)}</div>`; }
  if (c.is_bot) subEl.textContent = 'бот';
  else if (c.type === 'group') subEl.textContent = `${c.members_count || ''} участников`;
  else subEl.textContent = 'в сети';
  // Load messages
  document.getElementById('msg-area').innerHTML = '';
  lastMsgDate = null;
  const msgs = await api(`/api/chats/${chatId}/messages`);
  const area = document.getElementById('msg-area');
  msgs.forEach(m => appendMessage(m));
  area.scrollTop = area.scrollHeight;
  // Mark read
  allChats = allChats.map(x => x.id === chatId ? {...x, unread_count: 0} : x);
  renderChats();
}

function closeChat() {
  socket?.emit('leave', {chat_id: currentChatId});
  currentChatId = null;
  goBack();
}

function openChatProfile() {
  if (!currentChatData) return;
  if (currentChatData.other_user) openUserProfile(currentChatData.other_user.id);
}

// ═══════════════════ MESSAGES ═══════════════════
function appendMessage(m) {
  const area = document.getElementById('msg-area');
  const isOut = m.sender_id === me?.id;
  const date = new Date(m.created_at);
  const dateStr = date.toLocaleDateString('ru-RU', {day:'numeric', month:'long'});
  if (lastMsgDate !== dateStr) {
    const sep = document.createElement('div');
    sep.className = 'msg-date-sep';
    sep.innerHTML = `<span>${dateStr}</span>`;
    area.appendChild(sep);
    lastMsgDate = dateStr;
  }
  const wrap = document.createElement('div');
  wrap.className = `msg-wrap${isOut?' out':''}`;
  wrap.setAttribute('data-msg-id', m.id);
  // Avatar for incoming
  let avHtml = '';
  if (!isOut) {
    avHtml = `<div style="flex-shrink:0">${avatarHTML(m.sender_name, m.sender_avatar, m.sender_avatar_color, 32)}</div>`;
  }
  // Reply
  let replyHtml = '';
  if (m.reply_to) {
    replyHtml = `<div class="msg-reply"><div class="msg-reply-name">${escHtml(m.reply_to.sender_name)}</div><div>${escHtml(m.reply_to.text)}</div></div>`;
  }
  // Media
  let mediaHtml = '';
  if (m.media_b64 && m.media_type === 'image') {
    mediaHtml = `<img class="msg-img" src="${m.media_b64}" onclick="previewImg('${m.media_b64}')" style="max-width:220px;border-radius:8px;display:block;margin-bottom:4px">`;
  }
  // Sender name (groups)
  let senderHtml = '';
  if (!isOut && currentChatData?.type === 'group') {
    senderHtml = `<div class="msg-sender">${escHtml(m.sender_name)}</div>`;
  }
  // Reactions
  const reactions = m.reactions || {};
  const reactHtml = Object.keys(reactions).length ? `<div class="msg-reactions">` + Object.entries(reactions).map(([e, ids]) =>
    `<div class="reaction-pill${ids.includes(me?.id)?' mine':''}" onclick="sendReaction(${m.id},'${e}')">${e} ${ids.length}</div>`
  ).join('') + `</div>` : '';
  // Checks
  const readBy = m.read_by || [];
  const checkes = isOut ? (readBy.length > 1 ? `<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:var(--blue)"><path d="M.41 13.41L6 19l1.41-1.42L1.83 12zm20.4-6.83l-9.66 9.66-3.75-3.75-1.41 1.42 5.16 5.17L22.24 8l-1.42-1.42zM18 7l-1.41-1.42-7.08 7.07 1.41 1.41z"/></svg>` : `<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:var(--sec)"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>`) : '';
  const deletedStyle = m.deleted ? 'font-style:italic;color:var(--sec)' : '';
  const forwardedHtml = m.forwarded_from ? `<div style="font-size:12px;color:var(--blue);margin-bottom:4px">Переслано от ${escHtml(m.forwarded_from)}</div>` : '';
  wrap.innerHTML = `${avHtml}<div class="msg-bubble${isOut?' out':''}">
    ${senderHtml}${forwardedHtml}${replyHtml}${mediaHtml}
    <div class="msg-text" style="${deletedStyle}">${m.deleted ? 'Сообщение удалено' : escHtml(m.text)}</div>
    ${reactHtml}
    <div class="msg-meta">
      ${m.edited ? '<span style="font-size:11px;color:var(--sec)">ред.</span>' : ''}
      <span class="msg-time">${date.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</span>
      ${checkes}
    </div>
  </div>`;
  // Long press context menu
  wrap.querySelector('.msg-bubble').addEventListener('contextmenu', (e) => {
    e.preventDefault();
    showMsgCtx(e, m, isOut);
  });
  wrap.querySelector('.msg-bubble').addEventListener('touchstart', (e) => {
    const t = setTimeout(() => showMsgCtx(e.touches[0], m, isOut), 500);
    wrap.addEventListener('touchend', () => clearTimeout(t), {once:true});
    wrap.addEventListener('touchmove', () => clearTimeout(t), {once:true});
  });
  area.appendChild(wrap);
  // Scroll to bottom if near bottom
  if (area.scrollHeight - area.scrollTop - area.clientHeight < 200) {
    area.scrollTop = area.scrollHeight;
  }
}

function updateReactions(msgId, reactions) {
  const wrap = document.querySelector(`[data-msg-id="${msgId}"]`);
  if (!wrap) return;
  const existing = wrap.querySelector('.msg-reactions');
  const reactHtml = Object.keys(reactions).length ? `<div class="msg-reactions">` + Object.entries(reactions).map(([e, ids]) =>
    `<div class="reaction-pill${ids.includes(me?.id)?' mine':''}" onclick="sendReaction(${msgId},'${e}')">${e} ${ids.length}</div>`
  ).join('') + `</div>` : '';
  if (existing) existing.outerHTML = reactHtml;
  else { const meta = wrap.querySelector('.msg-meta'); if (meta) meta.insertAdjacentHTML('beforebegin', reactHtml); }
}

async function sendMsg() {
  const inp = document.getElementById('msg-input');
  const text = inp.value.trim();
  const area = document.getElementById('msg-area');
  if (!text && !pendingMedia) return;
  inp.value = ''; inp.style.height = '';
  const body = {text, reply_to_id: replyTo?.id || 0};
  if (pendingMedia) { body.media_b64 = pendingMedia.b64; body.media_type = pendingMedia.type; body.file_name = pendingMedia.name; pendingMedia = null; }
  cancelReply();
  try {
    await api(`/api/chats/${currentChatId}/send`, {method:'POST', body});
    area.scrollTop = area.scrollHeight;
  } catch(e) { notify(e.message, 'error'); }
}

function msgKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

let typingTimeout = null;
function onTyping() {
  if (!socket) return;
  socket.emit('typing', {chat_id: currentChatId});
}

function showTyping(name) {
  const bar = document.getElementById('typing-bar');
  document.getElementById('typing-text').textContent = `${name} печатает...`;
  bar.style.display = 'flex';
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => bar.style.display = 'none', 3000);
}

let replyToData = null;
function setReply(msg) {
  replyTo = msg;
  document.getElementById('reply-bar').style.display = 'flex';
  document.getElementById('reply-preview').innerHTML = `<strong>${escHtml(msg.sender_name)}</strong>: ${escHtml(msg.text || '[медиа]').substring(0, 60)}`;
  document.getElementById('msg-input').focus();
}

function cancelReply() {
  replyTo = null;
  document.getElementById('reply-bar').style.display = 'none';
}

function closePinnedBar() { document.getElementById('pinned-msg-bar').style.display = 'none'; }

// Context menu for messages
function showMsgCtx(e, msg, isOut) {
  closeCtx();
  const menu = document.getElementById('ctx-menu');
  let items = [
    {label: 'Ответить', action: () => { setReply(msg); closeCtx(); }},
    {label: 'Реакции', sub: ['👍','❤️','😂','🔥','😮','😢'].map(r => ({label: r, action: () => { sendReaction(msg.id, r); closeCtx(); }}))},
    {label: 'Переслать', action: () => { closeCtx(); notify('Функция в разработке'); }},
    {label: 'Копировать', action: () => { navigator.clipboard?.writeText(msg.text); closeCtx(); notify('Скопировано'); }},
  ];
  if (isOut || me?.is_admin) {
    items.push({label: 'Редактировать', action: () => { closeCtx(); editMsg(msg); }});
    items.push({label: 'Удалить', red: true, action: () => { closeCtx(); deleteMsg(msg.id); }});
  }
  menu.innerHTML = items.map(it => {
    if (it.sub) return `<div class="ctx-item" style="flex-wrap:wrap;gap:4px">${it.label}: ${it.sub.map(s => `<span onclick="${s.action.toString().includes('closeCtx')?'':''}(${s.label})" style="font-size:22px;cursor:pointer" onclick="(${s.action.toString()})()">${s.label}</span>`).join('')}</div>`;
    return `<div class="ctx-item${it.red?' red':''}" onclick="ctxActions['${it.label}']()">${it.label}</div>`;
  }).join('');
  window._ctxActions = {};
  items.forEach(it => { if (!it.sub) window._ctxActions[it.label] = it.action; });
  window.ctxActions = window._ctxActions;
  // Reactions row separate
  menu.innerHTML = `
    <div style="display:flex;justify-content:space-around;padding:8px 12px;border-bottom:.5px solid var(--div)">
      ${['👍','❤️','😂','🔥','😮','😢'].map(r => `<span style="font-size:24px;cursor:pointer" onclick="sendReaction(${msg.id},'${r}');closeCtx()">${r}</span>`).join('')}
    </div>
    ${isOut||me?.is_admin ? `<div class="ctx-item" onclick="editMsg_${msg.id}()">Редактировать</div><div class="ctx-item red" onclick="deleteMsg(${msg.id});closeCtx()">Удалить</div>` : ''}
    <div class="ctx-item" onclick="setReply(${JSON.stringify(msg).replace(/"/g,'&quot;')});closeCtx()">Ответить</div>
    <div class="ctx-item" onclick="navigator.clipboard&&navigator.clipboard.writeText('${escHtml(msg.text).replace(/'/g,"\\'")}');notify('Скопировано');closeCtx()">Копировать</div>
  `;
  // Attach edit function dynamically
  window[`editMsg_${msg.id}`] = () => { closeCtx(); editMsg(msg); };
  const x = Math.min(e.clientX || 100, window.innerWidth - 170);
  const y = Math.min(e.clientY || 200, window.innerHeight - 200);
  menu.style.cssText = `display:block;left:${x}px;top:${y}px`;
  document.addEventListener('click', closeCtx, {once: true});
}

function closeCtx() { document.getElementById('ctx-menu').style.display = 'none'; }

async function sendReaction(msgId, emoji) {
  if (!currentChatId) return;
  try { await api(`/api/chats/${currentChatId}/messages/${msgId}/react`, {method:'POST', body:{emoji}}); }
  catch(e) { notify(e.message,'error'); }
}

async function deleteMsg(msgId) {
  if (!confirm('Удалить сообщение?')) return;
  try { await api(`/api/chats/${currentChatId}/messages/${msgId}`, {method:'DELETE'}); }
  catch(e) { notify(e.message,'error'); }
}

function editMsg(msg) {
  const inp = document.getElementById('msg-input');
  inp.value = msg.text;
  autoResize(inp);
  inp.focus();
  inp.dataset.editId = msg.id;
  // Override send button temporarily
  const sendBtn = document.querySelector('.send-btn');
  sendBtn.onclick = async () => {
    const text = inp.value.trim();
    if (!text) return;
    try {
      await api(`/api/chats/${currentChatId}/messages/${msg.id}`, {method:'PUT', body:{text}});
      inp.value = ''; inp.style.height = '';
      delete inp.dataset.editId;
      sendBtn.onclick = sendMsg;
      notify('Изменено');
    } catch(e) { notify(e.message,'error'); }
  };
}

let pendingMedia = null;
function triggerAttach() { document.getElementById('file-input').click(); }
function handleFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    pendingMedia = {b64: e.target.result, type: file.type.startsWith('image/') ? 'image' : 'file', name: file.name};
    notify(`Прикреплено: ${file.name}`);
  };
  reader.readAsDataURL(file);
  input.value = '';
}

function chatCall() { notify('Голосовые звонки в разработке'); }
function chatMenu() {
  const menu = [
    {label: 'Профиль', action: openChatProfile},
    {label: currentChatData?.is_pinned ? 'Открепить' : 'Закрепить', action: () => pinChat()},
    {label: currentChatData?.is_muted ? 'Включить звук' : 'Отключить звук', action: () => muteChat()},
    {label: 'Пожаловаться', red: true, action: () => reportUser()},
  ];
  // Show as bottom sheet
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay show';
  overlay.innerHTML = `<div class="bottom-sheet" onclick="event.stopPropagation()">
    <div class="sheet-handle"></div>
    <div class="sheet-content">${menu.map((it,i) => `<div class="pcard-row${it.red?' red':''}" style="color:${it.red?'var(--red)':'var(--text)'}" data-idx="${i}">${it.label}</div>`).join('')}</div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.querySelectorAll('.pcard-row').forEach(el => {
    el.onclick = () => { menu[+el.dataset.idx].action(); document.body.removeChild(overlay); };
  });
  overlay.onclick = () => document.body.removeChild(overlay);
}

async function pinChat() {
  try { const r = await api(`/api/chats/${currentChatId}/pin`, {method:'POST'}); notify(r.pinned ? 'Закреплено' : 'Откреплено'); loadChats(); }
  catch(e) { notify(e.message,'error'); }
}
async function muteChat() {
  try { const r = await api(`/api/chats/${currentChatId}/mute`, {method:'POST'}); notify(r.muted ? 'Уведомления отключены' : 'Уведомления включены'); loadChats(); }
  catch(e) { notify(e.message,'error'); }
}
function reportUser() {
  if (!currentChatData?.other_user) { notify('Нельзя пожаловаться'); return; }
  const reason = prompt('Причина жалобы:');
  if (!reason) return;
  api('/api/report', {method:'POST', body:{target_id: currentChatData.other_user.id, reason}})
    .then(() => notify('Жалоба отправлена')).catch(e => notify(e.message,'error'));
}

// ═══════════════════ SEARCH ═══════════════════
function showSearch() { showScreen('s-search'); setTimeout(() => document.getElementById('search-input').focus(), 300); }

let searchDebounce;
async function doSearch(q) {
  clearTimeout(searchDebounce);
  if (!q.trim()) {
    document.getElementById('search-results').innerHTML = `<div class="empty-state"><svg viewBox="0 0 24 24"><path d="M15.5 14h-.79l-.28-.27A6.5 6.5 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16a6.5 6.5 0 0 0 4.23-1.57l.27.28v.79l5 4.99L20.49 19z"/></svg><h3>Найди людей и ботов</h3><p>Введи имя или @юзернейм</p></div>`;
    return;
  }
  searchDebounce = setTimeout(async () => {
    try {
      const users = await api(`/api/users/search?q=${encodeURIComponent(q)}`);
      const el = document.getElementById('search-results');
      if (!users.length) { el.innerHTML = `<div class="empty-state"><h3>Не найдено</h3></div>`; return; }
      el.innerHTML = users.map(u => `<div class="ci" onclick="openUserProfile(${u.id})">
        ${avatarHTML(u.display_name, u.avatar_b64, u.avatar_color, 50)}
        <div class="ci-body">
          <div class="ci-row"><div class="ci-name">${escHtml(u.display_name)}${u.badge==='official'?verifiedCheck():''}</div>${u.is_bot?'<span style="font-size:11px;color:var(--blue);background:rgba(42,171,238,.1);padding:2px 6px;border-radius:8px">бот</span>':''}</div>
          <div class="ci-row"><div class="ci-msg">@${escHtml(u.username)}</div></div>
        </div>
      </div>`).join('');
    } catch(e) {}
  }, 400);
}

// ═══════════════════ PROFILES ═══════════════════
async function openUserProfile(uid) {
  try {
    const u = await api(`/api/users/${uid}`);
    renderProfile(u);
    showScreen('s-profile');
  } catch(e) { notify(e.message,'error'); }
}

function renderProfile(u) {
  const el = document.getElementById('profile-content');
  const isMe = u.id === me?.id;
  const traits = u.bot_traits || [];
  el.innerHTML = `
    <div class="profile-header">
      ${avatarHTML(u.display_name, u.avatar_b64, u.avatar_color, 68)}
      <h2>${escHtml(u.display_name)}${u.badge==='official'?verifiedCheck():''}</h2>
      <p>@${u.username}</p>
      ${u.badge ? `<div class="badge badge-${u.badge}">${badgeLabel(u.badge)}</div>` : ''}
    </div>
    <div class="profile-content">
      ${u.bio ? `<div class="pcard"><div class="pcard-label">Описание</div><div class="pcard-value">${escHtml(u.bio)}</div></div>` : ''}
      ${u.is_bot ? `
        ${u.bot_appearance ? `<div class="pcard"><div class="pcard-label">Внешность</div><div class="pcard-value">${escHtml(u.bot_appearance)}</div></div>` : ''}
        ${u.bot_personality ? `<div class="pcard"><div class="pcard-label">Характер</div><div class="pcard-value">${escHtml(u.bot_personality)}</div></div>` : ''}
        ${u.bot_scenario ? `<div class="pcard"><div class="pcard-label">Сценарий</div><div class="pcard-value">${escHtml(u.bot_scenario)}</div></div>` : ''}
        ${traits.length ? `<div class="pcard"><div class="pcard-label">Черты</div><div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px">${traits.map(t=>`<span style="background:rgba(42,171,238,.1);color:var(--blue);padding:4px 10px;border-radius:12px;font-size:13px">${t}</span>`).join('')}</div></div>` : ''}
        <div style="padding:0 12px 12px">
          <button class="btn btn-blue" style="width:100%" onclick="startChatWith(${u.id})">Написать боту</button>
        </div>
      ` : `
        <div style="padding:0 12px 12px;display:flex;gap:10px">
          ${!isMe ? `<button class="btn btn-blue" style="flex:1" onclick="startChatWith(${u.id})">Написать</button>` : ''}
          ${isMe ? `<button class="btn btn-outline" style="flex:1" onclick="goEditProfile()">Редактировать</button>` : ''}
        </div>
      `}
      ${!isMe && !u.is_bot ? `<div style="padding:0 12px 16px"><button class="btn btn-gray" style="width:100%" onclick="reportProfile(${u.id})">Пожаловаться</button></div>` : ''}
    </div>
  `;
}

function profileMore() {}
function reportProfile(uid) {
  const reason = prompt('Причина:');
  if (!reason) return;
  api('/api/report', {method:'POST', body:{target_id: uid, reason}}).then(() => notify('Жалоба отправлена'));
}

async function startChatWith(uid) {
  try {
    const r = await api(`/api/chats/open/${uid}`, {method:'POST'});
    const c = r.chat;
    if (!allChats.find(x => x.id === c.id)) { await loadChats(); }
    goBack();
    openChat(c.id);
  } catch(e) { notify(e.message,'error'); }
}

// ═══════════════════ CREATE BOT ═══════════════════
function triggerBotAvatar() { document.getElementById('bot-av-input').click(); }
function setBotAvatar(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    botAvatarB64 = e.target.result;
    const prev = document.getElementById('bot-av-preview');
    prev.innerHTML = `<img src="${botAvatarB64}" style="width:100%;height:100%;border-radius:50%;object-fit:cover">`;
  };
  reader.readAsDataURL(file);
}

async function submitCreateBot() {
  const name = document.getElementById('bot-name').value.trim();
  const username = document.getElementById('bot-username').value.trim();
  const desc = document.getElementById('bot-desc').value.trim();
  const appearance = document.getElementById('bot-appearance').value.trim();
  const personality = document.getElementById('bot-personality').value.trim();
  const scenario = document.getElementById('bot-scenario').value.trim();
  if (!name || !username) { notify('Заполни имя и юзернейм', 'error'); return; }
  try {
    const r = await api('/api/bots/create', {method:'POST', body:{
      display_name: name, username, description: desc,
      appearance, personality, scenario,
      traits: selectedTraits, avatar_b64: botAvatarB64,
    }});
    notify('Бот создан!', 'success');
    // Clear form
    ['bot-name','bot-username','bot-desc','bot-appearance','bot-personality','bot-scenario']
      .forEach(id => document.getElementById(id).value = '');
    document.getElementById('bot-av-preview').innerHTML = `<svg viewBox="0 0 24 24" style="width:30px;height:30px;fill:rgba(255,255,255,.7)"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/></svg>`;
    selectedTraits = [];
    document.querySelectorAll('.trait-chip.sel').forEach(c => c.classList.remove('sel'));
    botAvatarB64 = '';
    await loadChats();
    openUserProfile(r.bot.id);
  } catch(e) { notify(e.message, 'error'); }
}

// ═══════════════════ SETTINGS & PROFILE ═══════════════════
function goSettings() { updateSettingsHeader(); showScreen('s-settings'); }

function updateSettingsHeader() {
  if (!me) return;
  const el = document.getElementById('settings-profile-header');
  el.innerHTML = `
    ${avatarHTML(me.display_name, me.avatar_b64, me.avatar_color, 68)}
    <h2>${escHtml(me.display_name)}</h2>
    <p>@${me.username}</p>
    ${me.is_admin ? `<div class="badge badge-official" style="margin-top:4px">Администратор</div>` : ''}
  `;
}

function goEditProfile() {
  if (!me) return;
  document.getElementById('edit-name').value = me.display_name;
  document.getElementById('edit-username').value = me.username;
  document.getElementById('edit-bio').value = me.bio || '';
  document.getElementById('edit-phone').value = me.phone || '';
  const prev = document.getElementById('edit-av-preview');
  prev.style.background = me.avatar_color;
  if (me.avatar_b64) prev.innerHTML = `<img src="${me.avatar_b64}" style="width:100%;height:100%;border-radius:50%;object-fit:cover">`;
  else prev.innerHTML = `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:24px;color:#fff">${getInitials(me.display_name)}</div>`;
  editAvatarB64 = me.avatar_b64 || '';
  showScreen('s-edit-profile');
}

function setEditAvatar(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    editAvatarB64 = e.target.result;
    const prev = document.getElementById('edit-av-preview');
    prev.innerHTML = `<img src="${editAvatarB64}" style="width:100%;height:100%;border-radius:50%;object-fit:cover">`;
  };
  reader.readAsDataURL(file);
}

async function saveProfile() {
  const display_name = document.getElementById('edit-name').value.trim();
  const username = document.getElementById('edit-username').value.trim();
  const bio = document.getElementById('edit-bio').value.trim();
  const phone = document.getElementById('edit-phone').value.trim();
  if (!display_name) { notify('Введи имя', 'error'); return; }
  try {
    const r = await api('/api/users/me', {method:'PUT', body:{display_name, username, bio, phone, avatar_b64: editAvatarB64}});
    me = r.user;
    updateSettingsHeader();
    notify('Сохранено', 'success');
    goBack();
  } catch(e) { notify(e.message,'error'); }
}

// ═══════════════════ NEW CHAT / GROUP ═══════════════════
function showNewMenu() { document.getElementById('new-menu-modal').classList.add('show'); }
function openNewChat() {
  document.getElementById('new-chat-modal').classList.add('show');
  document.getElementById('new-chat-results').innerHTML = '';
  setTimeout(() => document.getElementById('new-chat-search').focus(), 300);
}
function closeModal(id) { document.getElementById(id).classList.remove('show'); }

let ncSearchDebounce;
async function newChatSearch(q) {
  clearTimeout(ncSearchDebounce);
  ncSearchDebounce = setTimeout(async () => {
    if (!q.trim()) { document.getElementById('new-chat-results').innerHTML = ''; return; }
    try {
      const users = await api(`/api/users/search?q=${encodeURIComponent(q)}`);
      document.getElementById('new-chat-results').innerHTML = users.map(u => `
        <div class="ci" onclick="closeModal('new-chat-modal');startChatWith(${u.id})">
          ${avatarHTML(u.display_name, u.avatar_b64, u.avatar_color, 50)}
          <div class="ci-body">
            <div class="ci-row"><div class="ci-name">${escHtml(u.display_name)}${u.is_bot?` <span style="font-size:11px;color:var(--blue)">[бот]</span>`:''}</div></div>
            <div class="ci-row"><div class="ci-msg">@${u.username}</div></div>
          </div>
        </div>`).join('') || '<div style="padding:20px;text-align:center;color:var(--sec)">Не найдено</div>';
    } catch(e) {}
  }, 400);
}

async function openNewGroup() {
  const name = prompt('Название группы:');
  if (!name) return;
  try {
    const r = await api('/api/groups/create', {method:'POST', body:{name, member_ids:[]}});
    await loadChats();
    openChat(r.chat.id);
  } catch(e) { notify(e.message,'error'); }
}

// ═══════════════════ ADMIN ═══════════════════
function goAdmin() { adminTab('stats', document.querySelector('#s-admin .tabs .tab')); showScreen('s-admin'); }

async function adminTab(tab, el) {
  document.querySelectorAll('#s-admin .tab').forEach(t => t.classList.remove('on'));
  if (el) el.classList.add('on');
  const content = document.getElementById('admin-content');
  content.innerHTML = '<div style="padding:20px;text-align:center;color:var(--sec)">Загрузка...</div>';
  if (tab === 'stats') {
    const s = await api('/api/admin/stats');
    content.innerHTML = `<div style="padding:12px">
      <div class="admin-card">
        <div class="admin-card-title">Статистика</div>
        <div class="stat-grid">
          <div class="stat-cell"><div class="stat-num">${s.total_users}</div><div class="stat-lbl">Пользователей</div></div>
          <div class="stat-cell"><div class="stat-num">${s.total_bots}</div><div class="stat-lbl">Ботов</div></div>
          <div class="stat-cell"><div class="stat-num">${s.total_messages}</div><div class="stat-lbl">Сообщений</div></div>
          <div class="stat-cell"><div class="stat-num">${s.total_chats}</div><div class="stat-lbl">Чатов</div></div>
          <div class="stat-cell"><div class="stat-num">${s.online_users}</div><div class="stat-lbl">Онлайн</div></div>
          <div class="stat-cell"><div class="stat-num">${s.banned_users}</div><div class="stat-lbl">Заблок.</div></div>
        </div>
      </div>
      <div class="admin-card" style="margin-top:10px">
        <div class="admin-card-title">Рассылки</div>
        <div style="padding:10px 14px;font-size:15px">${s.broadcasts} рассылок отправлено</div>
      </div>
      ${s.reports > 0 ? `<div class="admin-card" style="margin-top:10px;border:1px solid var(--red)">
        <div class="admin-card-title" style="color:var(--red)">Жалобы</div>
        <div style="padding:10px 14px;font-size:15px;color:var(--red)">${s.reports} непросмотренных жалоб</div>
      </div>` : ''}
    </div>`;
  } else if (tab === 'users') {
    loadAdminUsers('', content);
  } else if (tab === 'broadcast') {
    const bs = await api('/api/admin/broadcasts');
    content.innerHTML = `<div style="padding:12px">
      <div class="admin-card">
        <div class="admin-card-title">Новая рассылка через @ArtGram</div>
        <div style="padding:12px">
          <textarea id="broadcast-text" class="form-textarea" style="background:var(--bg);border-radius:10px;padding:10px;width:100%;min-height:100px" placeholder="Текст рассылки всем пользователям..."></textarea>
          <button class="btn btn-blue" style="width:100%;margin-top:10px" onclick="sendBroadcast()">Отправить всем</button>
        </div>
      </div>
      ${bs.length ? `<div class="admin-card" style="margin-top:10px">
        <div class="admin-card-title">История рассылок</div>
        ${bs.map(b => `<div style="padding:10px 14px;border-bottom:.5px solid var(--div)">
          <div style="font-size:13px;color:var(--sec)">${new Date(b.created_at).toLocaleDateString('ru-RU')} — отправлено: ${b.sent_count}</div>
          <div style="font-size:14px;margin-top:4px">${escHtml(b.text).substring(0,100)}</div>
        </div>`).join('')}
      </div>` : ''}
    </div>`;
  } else if (tab === 'reports') {
    const reports = await api('/api/admin/reports');
    content.innerHTML = `<div style="padding:12px">` + (reports.length ? reports.map(r => `
      <div class="admin-card" style="margin-bottom:8px">
        <div style="padding:12px 14px">
          <div style="font-size:13px;color:var(--sec)">${new Date(r.created_at).toLocaleDateString('ru-RU')}</div>
          <div style="font-size:14px;margin:4px 0"><strong>@${r.reporter}</strong> на <strong>@${r.target}</strong></div>
          <div style="font-size:13px;color:var(--sec)">Причина: ${escHtml(r.reason)}</div>
          <div style="display:flex;gap:8px;margin-top:10px">
            <button class="btn btn-blue" style="flex:1;padding:8px" onclick="openAdminUser_id(${r.target_id})">Открыть профиль</button>
            ${!r.reviewed ? `<button class="btn btn-gray" style="flex:1;padding:8px" onclick="reviewReport(${r.id},this)">Рассмотрено</button>` : '<span style="font-size:13px;color:var(--green);padding:8px">Рассмотрено</span>'}
          </div>
        </div>
      </div>`).join('') : '<div style="padding:20px;text-align:center;color:var(--sec)">Жалоб нет</div>') + `</div>`;
  }
}

function openAdminUser_id(uid) { openAdminUserEdit(uid); }
async function reviewReport(rid, btn) {
  await api(`/api/admin/reports/${rid}/review`, {method:'POST'});
  btn.textContent = 'Рассмотрено'; btn.disabled = true;
}

async function loadAdminUsers(q, container) {
  const data = await api(`/api/admin/users?q=${encodeURIComponent(q)}&page=1`);
  container.innerHTML = `<div style="padding:8px 12px">
    <input class="search-input" placeholder="Поиск пользователя..." value="${escHtml(q)}" oninput="loadAdminUsers(this.value,document.getElementById('admin-content'))">
  </div>
  <div style="padding:0 12px">` +
  data.users.map(u => `<div class="ci" onclick="openAdminUserEdit(${u.id})" style="border-radius:10px;margin-bottom:4px">
    ${avatarHTML(u.display_name, u.avatar_b64, u.avatar_color, 46)}
    <div class="ci-body">
      <div class="ci-row">
        <div class="ci-name" style="font-size:14px">${escHtml(u.display_name)}${u.is_admin?' [ADMIN]':''}</div>
        ${u.is_banned ? '<span style="font-size:11px;color:var(--red);background:rgba(229,57,53,.1);padding:2px 6px;border-radius:6px">БАНТ</span>' : ''}
      </div>
      <div class="ci-row"><div class="ci-msg">@${u.username} ${u.is_bot?'[BOT]':''}</div></div>
    </div>
    <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:var(--sec)"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
  </div>`).join('') + `</div>
  <div style="padding:12px;text-align:center;font-size:13px;color:var(--sec)">Всего: ${data.total}</div>`;
}

async function openAdminUserEdit(uid) {
  adminUserId = uid;
  const u = await api(`/api/admin/users/${uid}`);
  const content = document.getElementById('admin-user-content');
  content.innerHTML = `
    <div style="background:linear-gradient(135deg,var(--blue),#1a8fd1);padding:16px;display:flex;flex-direction:column;align-items:center;gap:8px">
      ${avatarHTML(u.display_name, u.avatar_b64, u.avatar_color, 60)}
      <div style="font-size:18px;font-weight:600;color:#fff">${escHtml(u.display_name)}</div>
      <div style="font-size:13px;color:rgba(255,255,255,.8)">@${u.username} · ID: ${u.id}</div>
      ${u.is_banned ? '<div class="badge badge-scam">ЗАБЛОКИРОВАН</div>' : ''}
    </div>
    <div style="padding:12px">
      <!-- Quick actions -->
      <div class="admin-card">
        <div class="admin-card-title">Быстрые действия</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px">
          <button class="btn ${u.is_banned?'btn-blue':'btn-red'}" style="padding:10px;font-size:13px" onclick="adminToggleBan(${u.id},${u.is_banned})">${u.is_banned ? 'Разблокировать' : 'Заблокировать'}</button>
          <button class="btn btn-outline" style="padding:10px;font-size:13px" onclick="adminEditUserForm(${u.id})">Редактировать</button>
          <button class="btn btn-gray" style="padding:10px;font-size:13px" onclick="adminSetBadge(${u.id})">Метка</button>
          <button class="btn btn-gray" style="padding:10px;font-size:13px" onclick="adminChangeUsername(${u.id})">Юзернейм</button>
        </div>
      </div>
      <!-- Badges -->
      <div class="admin-card" style="margin-top:8px">
        <div class="admin-card-title">Метки</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;padding:12px">
          ${['official','verified','scam','fake',''].map(b => `<div onclick="setUserBadge(${u.id},'${b}')" style="padding:7px 14px;border-radius:20px;cursor:pointer;font-size:13px;${u.badge===b?'background:var(--blue);color:#fff':'background:var(--bg);color:var(--text)'}">${b||'Без метки'}</div>`).join('')}
        </div>
      </div>
      <!-- Info -->
      <div class="admin-card" style="margin-top:8px">
        <div class="admin-card-title">Информация</div>
        <div style="padding:10px 14px">
          <div style="font-size:13px;color:var(--sec)">Телефон: ${u.phone||'—'}</div>
          <div style="font-size:13px;color:var(--sec);margin-top:4px">Регистрация: ${new Date(u.created_at).toLocaleDateString('ru-RU')}</div>
          <div style="font-size:13px;color:var(--sec);margin-top:4px">Последний раз: ${u.last_seen?new Date(u.last_seen).toLocaleDateString('ru-RU'):'—'}</div>
          ${u.is_bot ? `<div style="font-size:13px;color:var(--sec);margin-top:4px">Диалогов: ${u.bot_chat_count}</div>` : ''}
        </div>
      </div>
    </div>
  `;
  showScreen('s-admin-edit');
}

async function adminToggleBan(uid, isBanned) {
  if (!confirm(isBanned ? 'Разблокировать?' : 'Заблокировать пользователя?')) return;
  try {
    await api(`/api/admin/users/${uid}/ban`, {method:'POST'});
    notify(isBanned ? 'Разблокирован' : 'Заблокирован', 'success');
    openAdminUserEdit(uid);
  } catch(e) { notify(e.message,'error'); }
}

async function setUserBadge(uid, badge) {
  try {
    await api(`/api/admin/users/${uid}/badge`, {method:'POST', body:{badge}});
    notify('Метка установлена', 'success');
    openAdminUserEdit(uid);
  } catch(e) { notify(e.message,'error'); }
}

function adminSetBadge(uid) {
  const badge = prompt('Метка (official/verified/scam/fake или пусто):');
  if (badge === null) return;
  setUserBadge(uid, badge.trim());
}

function adminChangeUsername(uid) {
  const username = prompt('Новый юзернейм:');
  if (!username) return;
  api(`/api/admin/users/${uid}/username`, {method:'POST', body:{username}})
    .then(() => { notify('Юзернейм изменён', 'success'); openAdminUserEdit(uid); })
    .catch(e => notify(e.message,'error'));
}

function adminEditUserForm(uid) {
  api(`/api/admin/users/${uid}`).then(u => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay show';
    overlay.innerHTML = `<div class="bottom-sheet" onclick="event.stopPropagation()" style="max-height:80vh">
      <div class="sheet-handle"></div>
      <div class="sheet-title">Редактировать пользователя</div>
      <div class="sheet-content" style="padding:12px 16px 20px;display:flex;flex-direction:column;gap:10px">
        <input class="auth-input" id="aedit-name" value="${escHtml(u.display_name)}" placeholder="Имя">
        <textarea class="auth-input" id="aedit-bio" style="height:80px;resize:none" placeholder="Биография">${escHtml(u.bio||'')}</textarea>
        <button class="btn btn-blue" onclick="saveAdminUserEdit(${uid})">Сохранить</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.onclick = (e) => { if (e.target===overlay) document.body.removeChild(overlay); };
    window._adminEditOverlay = overlay;
  });
}

async function saveAdminUserEdit(uid) {
  const display_name = document.getElementById('aedit-name').value.trim();
  const bio = document.getElementById('aedit-bio').value.trim();
  try {
    await api(`/api/admin/users/${uid}`, {method:'PUT', body:{display_name, bio}});
    if (window._adminEditOverlay) document.body.removeChild(window._adminEditOverlay);
    notify('Сохранено', 'success');
    openAdminUserEdit(uid);
  } catch(e) { notify(e.message,'error'); }
}

async function sendBroadcast() {
  const text = document.getElementById('broadcast-text').value.trim();
  if (!text) { notify('Введи текст', 'error'); return; }
  if (!confirm(`Отправить рассылку всем пользователям?\n\n"${text.substring(0,100)}"`)) return;
  try {
    const r = await api('/api/admin/broadcast', {method:'POST', body:{text}});
    notify(`Отправлено: ${r.sent} пользователей`, 'success');
    document.getElementById('broadcast-text').value = '';
    adminTab('broadcast', null);
  } catch(e) { notify(e.message,'error'); }
}

// ═══════════════════ HELPERS ═══════════════════
function avatarHTML(name, b64, color, size) {
  const cls = size <= 34 ? 'av av-sm' : size >= 60 ? 'av av-lg' : 'av';
  if (b64) return `<div class="${cls}" style="width:${size}px;height:${size}px;background:${color||'#2AABEE'}"><img src="${b64}" style="width:100%;height:100%;object-fit:cover"></div>`;
  return `<div class="${cls}" style="width:${size}px;height:${size}px;background:${color||'#2AABEE'};font-size:${Math.floor(size*0.35)}px">${getInitials(name)}</div>`;
}

function getInitials(name) {
  if (!name) return '?';
  const parts = name.split(' ');
  return parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : name.substring(0,2).toUpperCase();
}

function badgeHTML(badge) {
  if (!badge) return '';
  return `<span class="badge badge-${badge}" style="margin-left:4px;font-size:10px">${badgeLabel(badge)}</span>`;
}

function badgeLabel(badge) {
  const labels = {official:'Официальный', verified:'Верифицированный', scam:'Мошенник', fake:'Фейк'};
  return labels[badge] || badge;
}

function verifiedCheck() {
  return `<span class="vcheck"><svg viewBox="0 0 10 10" fill="none"><path d="M1.5 5L4 7.5L8.5 2.5" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;
}

function formatTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const diff = now - d;
  if (diff < 86400000 && d.getDate() === now.getDate()) return d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
  if (diff < 7 * 86400000) return d.toLocaleDateString('ru-RU',{weekday:'short'});
  return d.toLocaleDateString('ru-RU',{day:'numeric',month:'short'});
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function notify(msg, type = '') {
  const el = document.createElement('div');
  el.className = `notif${type?' '+type:''}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity='0'; el.style.transition='opacity .3s'; setTimeout(() => el.remove(), 300); }, 2500);
}

function previewImg(src) {
  document.getElementById('img-preview-img').src = src;
  document.getElementById('img-preview').classList.add('show');
}
function closeImgPreview() { document.getElementById('img-preview').classList.remove('show'); }
</script>
</body>
</html>"""

# ═══════════════════════════ SERVE HTML ═══════════════════════════

@app.route('/')
def index():
    from flask import Response
    return Response(HTML, mimetype='text/html')

# ═══════════════════════════ STARTUP ═══════════════════════════

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_admin()
        ensure_artgram_bot()
        print("""
╔══════════════════════════════════════╗
║          ArtGramm запущен!           ║
║                                      ║
║  Открой: http://localhost:5000       ║
║                                      ║
║  Войти как admin: admin / admin123   ║
║  Или зарегистрируй новый аккаунт     ║
╚══════════════════════════════════════╝
        """)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
