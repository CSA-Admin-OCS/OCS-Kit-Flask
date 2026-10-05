# 🎉 Social Media Backend - Setup Complete!

Your social media backend is now fully integrated and ready to use!

## ✅ What Was Done

### 1. Backend Files Installed
- ✅ **`model/post.py`** - Database model for posts and replies
- ✅ **`api/post.py`** - REST API endpoints with JWT authentication
- ✅ **`scripts/init_posts.py`** - Database initialization script

### 2. Integration Complete
- ✅ Imported `post_api` blueprint in `main.py`
- ✅ Registered `/api/post` endpoints
- ✅ Added automatic database table creation on startup
- ✅ Connected to existing User authentication system

### 3. Frontend Files Ready
Your frontend files are in the `Social Media/` folder:
- **`post.md`** - Create posts and view feed page
- **`feed.md`** - Social feed viewer with filters

---

## 🚀 How to Use

### Step 1: Start Your Backend

```bash
cd ~/flaskbackend
python main.py
```

The posts table will be created automatically when the backend starts!

### Step 2: Copy Frontend Files

Move the markdown files to your frontend repository:

```bash
# Example: Copy to your pages repository
cp "~/flaskbackend/Social Media/post.md" ~/pages/navigation/social_media/
cp "~/flaskbackend/Social Media/feed.md" ~/pages/navigation/social_media/
```

### Step 3: Access Social Media

Once both backend and frontend are running:

1. **Login** to your account at `http://localhost:4100/login`
2. **Navigate** to `http://localhost:4100/social-media`
3. **Create posts**, view feed, and reply to classmates!

---

## 📡 API Endpoints

All endpoints require JWT authentication (except where noted):

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| `POST` | `/api/post` | Create a new post | ✅ Yes |
| `GET` | `/api/post/all` | Get all posts with replies | ✅ Yes |
| `GET` | `/api/post/<id>` | Get a specific post | ✅ Yes |
| `PUT` | `/api/post/<id>` | Update your post | ✅ Yes |
| `DELETE` | `/api/post/<id>` | Delete your post | ✅ Yes |
| `POST` | `/api/post/reply` | Reply to a post | ✅ Yes |
| `GET` | `/api/post/user/<user_id>` | Get posts by user | ✅ Yes |
| `GET` | `/api/post/page?url=<url>` | Get posts for a page | ❌ No |

---

## 🧪 Testing the API

### Test 1: Check if Posts API is Running

```bash
# This should return an authentication error (which means the API is working!)
curl http://localhost:8587/api/post/all
```

Expected response:
```json
{
  "message": "Token is missing"
}
```

### Test 2: Create a Post (After Login)

```bash
curl -X POST http://localhost:8587/api/post \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Hello from the social media platform!",
    "gradeReceived": "A+ (97-100%)"
  }'
```

### Test 3: View All Posts

```bash
curl http://localhost:8587/api/post/all \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

---

## 📊 Database Schema

The `posts` table includes:

```python
- id (Primary Key)
- user_id (Foreign Key to users table)
- parent_id (For threaded replies, nullable)
- content (Post text)
- grade_received (Optional grade)
- page_url (Optional lesson URL)
- page_title (Optional lesson title)
- timestamp (Auto-generated)
- updated_at (Auto-updated)
```

**Features:**
- ✅ Threaded comments (posts can have replies)
- ✅ User authentication required
- ✅ Grade tracking per post
- ✅ Lesson/page associations
- ✅ Timestamps for sorting

---

## 🎨 Frontend Features

### post.md (Create Post Page)
- Create new posts with optional grade
- View feed with all posts
- Reply to posts
- Real-time updates
- Login required to post

### feed.md (Social Feed Page)
- View all student posts
- Filter by grade or student name
- See reply counts and threads
- Stats dashboard (total posts, replies, active students)
- Auto-refresh every 30 seconds

---

## 🔧 Customization

### Add Sample Posts

You can manually add sample posts by running:

```bash
cd ~/flaskbackend
python scripts/init_posts.py
```

Or programmatically in Python:

```python
from model.post import Post

new_post = Post(
    user_id=1,
    content="My first post!",
    grade_received="A+ (97-100%)"
)
new_post.create()
```

### Modify Grade Options

Edit the grade dropdown in `post.md` (lines 416-430):

```html
<option value="A+ (97-100%)">A+ (97-100%)</option>
```

---

## 🛠️ Troubleshooting

### Issue: "Posts API not found"
**Solution:** Make sure you restarted your Flask backend after the changes.

### Issue: "Token is missing"
**Solution:** You need to login first. The frontend handles this automatically.

### Issue: "No posts showing"
**Solution:** 
1. Check backend is running: `http://localhost:8587/api/post/all`
2. Make sure you're logged in on the frontend
3. Create a test post to verify

### Issue: Database not created
**Solution:** The database is created automatically when you run `main.py`. Check your instance folder for the database file.

---

## 📱 User Flow

```
1. User visits frontend → Checks authentication
2. User clicks "Social Media" in navigation
3. Loads post.md page
4. User can:
   - Switch to "Create Post" tab
   - Write content and select grade (optional)
   - Submit post → Sends to /api/post
   - Switch to "View Feed" tab
   - See all posts with replies
   - Click "Reply" on any post
   - Submit reply → Sends to /api/post/reply
5. Posts are stored in database
6. All authenticated users can view
```

---

## 🎓 Educational Features

This social media platform is designed for classroom use:

- **Grade Sharing** - Students can share their grades (optional)
- **Lesson Feedback** - Posts can be linked to specific lessons
- **Peer Learning** - Students can reply and help each other
- **Progress Tracking** - Teachers can see student engagement
- **Safe Environment** - Only authenticated students can post

---

## 🔐 Security

- ✅ JWT authentication required for all POST/PUT/DELETE operations
- ✅ Users can only edit/delete their own posts
- ✅ Input sanitization to prevent XSS attacks
- ✅ Database transactions for data integrity
- ✅ CORS properly configured

---

## 📈 Next Steps

1. **Customize the UI** - Edit the CSS in the .md files to match your theme
2. **Add Notifications** - Notify users when they get replies
3. **Add Reactions** - Like/emoji reactions to posts
4. **Add Media** - Allow image uploads with posts
5. **Add Moderation** - Teacher can moderate/delete posts
6. **Add Analytics** - Track engagement metrics

---

## 🆘 Support

If you encounter any issues:

1. Check the Flask backend logs
2. Check browser console for frontend errors
3. Verify JWT token is being sent with requests
4. Ensure database tables were created

---

## 🎉 You're All Set!

Your social media backend is connected and ready to use! 

**Quick Test:**
1. Start backend: `python main.py`
2. Login to frontend
3. Go to `/social-media`
4. Create your first post!

Happy coding! 🚀

