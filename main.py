import io
import os
from datetime import date
from typing import Optional
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
from pydantic import BaseModel
from sqlalchemy import Column, Date, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# 1. إعداد التطبيق
app = FastAPI(title="نظام مكتبة دار الثقافة - أدرار")

# ربط المجلد الحالي لخدمة الملفات الثابتة (الصور)
app.mount("/static", StaticFiles(directory="."), name="static")

templates = Jinja2Templates(directory="templates")

# 2. إعداد قاعدة البيانات المحلية SQLite
SQLALCHEMY_DATABASE_URL = "sqlite:///./library.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Book(Base):
  __tablename__ = "books"
  id = Column(Integer, primary_key=True, index=True)
  book_number = Column(String, index=True, nullable=True)
  title = Column(String, index=True)
  author = Column(String, index=True)
  category = Column(String, index=True)
  total_copies = Column(Integer, default=1)


class Reservation(Base):
  __tablename__ = "reservations"
  id = Column(Integer, primary_key=True, index=True)
  book_id = Column(Integer)
  user_name = Column(String)
  reservation_date = Column(Date)


Base.metadata.create_all(bind=engine)


def get_db():
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()


class ReservationCreate(BaseModel):
  book_id: int
  user_name: str
  reservation_date: date


# الصفحة الرئيسية للزوار
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, db: Session = Depends(get_db)):
  books = db.query(Book).limit(50).all()
  return templates.TemplateResponse(request, "index.html", {"books": books})


# API للبحث عن الكتب
@app.get("/api/books")
def search_books(query: Optional[str] = None, db: Session = Depends(get_db)):
  if query:
    books = (
        db.query(Book)
        .filter(
            Book.title.contains(query)
            | Book.author.contains(query)
            | Book.category.contains(query)
            | Book.book_number.contains(query)
        )
        .all()
    )
  else:
    books = db.query(Book).limit(50).all()
  return books


# API لجلب الكتب حسب التصنيف المحدد
@app.get("/api/books/category/{category_name}")
def get_books_by_category(category_name: str, db: Session = Depends(get_db)):
  books = db.query(Book).filter(Book.category == category_name).all()
  return books


# API لإحصائيات قاعدة البيانات والتصنيفات
@app.get("/api/stats")
def get_database_stats(db: Session = Depends(get_db)):
  total_books = db.query(Book).count()
  categories = db.query(Book.category).distinct().all()
  cat_list = [c[0] for c in categories if c[0]]
  return {
      "total_books": total_books,
      "categories_count": len(cat_list),
      "categories": cat_list,
  }


# API لتسجيل حجز جديد
@app.post("/api/reserve")
def reserve_book(reservation: ReservationCreate, db: Session = Depends(get_db)):
  book = db.query(Book).filter(Book.id == reservation.book_id).first()
  if not book:
    raise HTTPException(status_code=404, detail="الكتاب غير موجود")

  new_res = Reservation(
      book_id=reservation.book_id,
      user_name=reservation.user_name,
      reservation_date=reservation.reservation_date,
  )
  db.add(new_res)
  db.commit()
  db.refresh(new_res)
  return {
      "message": (
          "تم تسجيل طلب حجز الكتاب بنجاح! سيتم التواصل معك عند جاهزيته."
      ),
      "reservation_id": new_res.id,
      "date": str(new_res.reservation_date),
  }


# API لعرض الحجوزات
@app.get("/api/reservations")
def get_reservations(db: Session = Depends(get_db)):
  results = []
  reservations = db.query(Reservation).all()
  for r in reservations:
    book = db.query(Book).filter(Book.id == r.book_id).first()
    results.append({
        "reservation_id": r.id,
        "user_name": r.user_name,
        "reservation_date": str(r.reservation_date),
        "book_title": book.title if book else "كتاب غير معروف",
        "book_number": book.book_number if book else "",
    })
  return results


# API استيراد الكتب من ملفات Excel مع حماية بكلمة السر
@app.post("/api/upload-excel")
def upload_excel(
    category_name: str = "تاريخ",
    admin_password: str = "",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
  if admin_password != "admin123":
    raise HTTPException(
        status_code=403, detail="كلمة سر أمين المكتبة غير صحيحة!"
    )

  try:
    contents = file.file.read()
    df = pd.read_excel(io.BytesIO(contents), header=None)

    added_count = 0
    for index, row in df.iloc[2:].iterrows():
      b_num = (
          str(row.iloc[0]).strip()
          if pd.notna(row.iloc[0]) and str(row.iloc[0]) != "nan"
          else ""
      )
      title = (
          str(row.iloc[1]).strip()
          if pd.notna(row.iloc[1]) and str(row.iloc[1]) != "nan"
          else ""
      )
      author = (
          str(row.iloc[2]).strip()
          if pd.notna(row.iloc[2]) and str(row.iloc[2]) != "nan"
          else "غير معروف"
      )
      note = (
          str(row.iloc[3]).strip()
          if pd.notna(row.iloc[3]) and str(row.iloc[3]) != "nan"
          else ""
      )

      if title:
        full_title = f"{title} ({note})" if note else title
        book = Book(
            book_number=b_num,
            title=full_title,
            author=author,
            category=category_name,
            total_copies=1,
        )
        db.add(book)
        added_count += 1

    db.commit()
    return {
        "message": (
            f"تمت إضافة {added_count} كتاباً في تصنيف '{category_name}' بنجاح!"
        )
    }
  except Exception as e:
    return {"error": str(e)}


# ==========================================
# نظام حماية لوحة التحكم (Admin Authentication)
# ==========================================


# صفحة تسجيل الدخول للوحة التحكم
@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
  return """
    <!DOCTYPE html>
    <html lang="ar" dir="rtl">
    <head>
        <meta charset="UTF-8">
        <title>تسجيل دخول أمين المكتبة</title>
        <style>
            body { font-family: Tahoma, sans-serif; background-color: #0f172a; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; direction: rtl; }
            .login-card { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); width: 100%; max-width: 350px; text-align: center; }
            .login-card h2 { color: #881337; margin-bottom: 20px; font-size: 20px; }
            .login-card input { width: 100%; padding: 12px; margin-bottom: 15px; border: 1px solid #cbd5e1; border-radius: 5px; box-sizing: border-box; font-size: 14px; }
            .login-card button { width: 100%; background-color: #e11d48; color: white; border: none; padding: 12px; border-radius: 5px; font-weight: bold; cursor: pointer; font-size: 15px; }
            .login-card button:hover { background-color: #be123c; }
        </style>
    </head>
    <body>
        <div class="login-card">
            <h2>🔒 بوابة أمين المكتبة</h2>
            <form action="/admin/login" method="POST">
                <input type="password" name="password" placeholder="أدخل كلمة سر أمين المكتبة" required>
                <button type="submit">دخول لوحة التحكم</button>
            </form>
        </div>
    </body>
    </html>
    """


# التحقق من كلمة السر ومنح صلاحية الجلسة
@app.post("/admin/login")
def admin_login(response: Response, password: str = Form(...)):
  if password != "admin123":
    return RedirectResponse(url="/admin/login", status_code=303)

  resp = RedirectResponse(url="/admin", status_code=303)
  resp.set_cookie(
      key="admin_session", value="authenticated", httponly=True, max_age=86400
  )
  return resp


# مسار لوحة التحكم المحمي (يتطلب كلمة السر)
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin_session: Optional[str] = Cookie(None),
):
  if admin_session != "authenticated":
    return RedirectResponse(url="/admin/login", status_code=303)

  reservations = db.query(Reservation).all()
  books = db.query(Book).all()
  return templates.TemplateResponse(
      request, "admin.html", {"reservations": reservations, "books": books}
  )


# زر لتسجيل الخروج
@app.get("/admin/logout")
def admin_logout():
  resp = RedirectResponse(url="/admin/login", status_code=303)
  resp.delete_cookie(key="admin_session")
  return resp
