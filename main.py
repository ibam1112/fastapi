from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
import re

# تكوين قاعدة البيانات
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'Ib1234567am#',
    'charset': 'utf8mb4',
    'database': 'births_db'
}

app = FastAPI(title="نظام تسجيل المواليد")

# إضافة CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit default port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# نموذج البيانات
class BirthData(BaseModel):
    father_id: str = Field(..., pattern=r'^\d{8,12}$', description="رقم هوية الأب")
    father_id_type: str = Field(..., description="نوع مستمسك الأب")
    father_full_name: str = Field(..., min_length=2, max_length=100, description="اسم الأب الرباعي")
    mother_id: str = Field(..., description="رقم هوية الأم", pattern=r'^\d{8,12}$')
    mother_id_type: str = Field(..., description="نوع مستمسك الأم")
    mother_name: str = Field(..., min_length=2, max_length=100, description="اسم الأم")
    hospital_name: str = Field(..., min_length=2, max_length=100, description="اسم المستشفى")
    birth_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="تاريخ الميلاد (YYYY-MM-DD)")

    @validator('father_id')
    def validate_father_id(cls, v, values):
        if not v.isdigit():
            raise ValueError("يجب أن يحتوي رقم الهوية على أرقام فقط")
        if values.get('father_id_type') == "موحدة" and len(v) != 12:
            raise ValueError("رقم الموحدة للأب يجب أن يكون 12 رقم")
        elif values.get('father_id_type') == "هوية_احوال" and len(v) != 8:
            raise ValueError("رقم هوية الأحوال للأب يجب أن يكون 8 أرقام")
        return v

    @validator('mother_id')
    def validate_mother_id(cls, v, values):
        if not v.isdigit():
            raise ValueError("يجب أن يحتوي رقم الهوية على أرقام فقط")
        if values.get('mother_id_type') == "موحدة" and len(v) != 12:
            raise ValueError("رقم الموحدة للأم يجب أن يكون 12 رقم")
        elif values.get('mother_id_type') == "هوية_احوال" and len(v) != 8:
            raise ValueError("رقم هوية الأحوال للأم يجب أن يكون 8 أرقام")
        return v

    @validator('father_full_name', 'mother_name', 'hospital_name')
    def validate_arabic_name(cls, v):
        if not re.match(r'^[\u0600-\u06FF\s]{2,100}$', v):
            raise ValueError("يجب أن يحتوي الاسم على حروف عربية فقط")
        return v

    @validator('birth_date')
    def validate_birth_date(cls, v):
        try:
            date = datetime.strptime(v, "%Y-%m-%d")
            today = datetime.now()
            if date > today:
                raise ValueError("لا يمكن أن يكون تاريخ الميلاد في المستقبل")
            if date.year < 1900:
                raise ValueError("تاريخ الميلاد غير صالح")
            if (today - date).days > 45:  # التحقق من أن التاريخ ليس قديماً جداً
                raise ValueError("لا يمكن تسجيل مواليد بعد 45 يوم من الولادة")
            return v
        except ValueError as e:
            raise ValueError(str(e))

    @validator('father_id_type', 'mother_id_type')
    def validate_id_type(cls, v):
        valid_types = ['موحدة', 'هوية_احوال']
        if v not in valid_types:
            raise ValueError(f"نوع الهوية يجب أن يكون أحد القيم التالية: {', '.join(valid_types)}")
        return v

# إدارة قاعدة البيانات
class DatabaseManager:
    def __init__(self):
        self.config = DB_CONFIG.copy()
        self._test_connection()
        self.create_database()
        self.init_db()
    
    def _test_connection(self):
        try:
            conn = mysql.connector.connect(
                host=self.config['host'],
                user=self.config['user'],
                password=self.config['password']
            )
            conn.close()
        except Error as e:
            print(f"❌ خطأ في الاتصال بقاعدة البيانات: {e}")
            raise HTTPException(
                status_code=500, 
                detail="فشل الاتصال بقاعدة البيانات. تأكد من تشغيل MySQL"
            )

    def create_database(self):
        temp_config = self.config.copy()
        temp_config.pop('database', None)
        try:
            conn = mysql.connector.connect(**temp_config)
            cursor = conn.cursor()
            
            # إنشاء قاعدة البيانات مع دعم كامل للغة العربية
            cursor.execute(f"""
                CREATE DATABASE IF NOT EXISTS {self.config['database']}
                CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            
            # التأكد من إعدادات الترميز
            cursor.execute(f"ALTER DATABASE {self.config['database']} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            
            cursor.close()
            conn.close()
        except Error as e:
            raise HTTPException(status_code=500, detail=f"خطأ في إنشاء قاعدة البيانات: {str(e)}")

    def init_db(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS births (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    father_id VARCHAR(12) NOT NULL,
                    father_id_type ENUM('موحدة', 'هوية_احوال') NOT NULL,
                    father_full_name VARCHAR(100) NOT NULL,
                    mother_id VARCHAR(12) NOT NULL,
                    mother_id_type ENUM('موحدة', 'هوية_احوال') NOT NULL,
                    mother_name VARCHAR(100) NOT NULL,
                    hospital_name VARCHAR(100) NOT NULL,
                    birth_date DATE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY unique_parents (father_id, mother_id),
                    INDEX idx_search (father_id, mother_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                conn.commit()
                print("✅ تم إنشاء الجدول بنجاح")
        except Error as e:
            print(f"❌ خطأ في إنشاء الجدول: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = mysql.connector.connect(**self.config)
            # تعيين الترميز للاتصال
            conn.set_charset_collation('utf8mb4', 'utf8mb4_unicode_ci')
            yield conn
        finally:
            if conn and conn.is_connected():  # Fixed: replaced && with and
                conn.close()

# تهيئة قاعدة البيانات
db_manager = DatabaseManager()

# تحديث دالة save_data لتحسين الاستجابة
@app.post("/save-data/")
async def save_data(data: BirthData):
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            # فحص وجود السجل
            cursor.execute("""
                SELECT id FROM births 
                WHERE father_id = %s AND mother_id = %s
                AND birth_date = %s
            """, (data.father_id, data.mother_id, data.birth_date))
            
            if cursor.fetchone():
                raise HTTPException(
                    status_code=400, 
                    detail="تم تسجيل مولود لنفس الأبوين بنفس تاريخ الميلاد مسبقاً"
                )
            
            try:
                # إدخال البيانات
                cursor.execute("""
                    INSERT INTO births (
                        father_id, father_id_type, father_full_name,
                        mother_id, mother_id_type, mother_name,
                        hospital_name, birth_date
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                    data.father_id, data.father_id_type, data.father_full_name,
                    data.mother_id, data.mother_id_type, data.mother_name,
                    data.hospital_name, data.birth_date
                ))
                conn.commit()
                
                # التحقق من نجاح الإدخال
                cursor.execute("""
                    SELECT * FROM births 
                    WHERE father_id = %s AND mother_id = %s
                    """, (data.father_id, data.mother_id))
                saved_data = cursor.fetchone()
                
                if saved_data:
                    return {
                        "message": "تم حفظ البيانات بنجاح",
                        "success": True,
                        "data": {
                            "id": saved_data["id"],
                            "created_at": saved_data["created_at"].isoformat()
                        }
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail="تم إدخال البيانات ولكن لم يتم التأكد من حفظها"
                    )
                    
            except Error as e:
                conn.rollback()
                raise HTTPException(status_code=500, detail=f"خطأ في حفظ البيانات: {str(e)}")
                
    except Error as e:
        print(f"❌ خطأ في حفظ البيانات: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/statistics")
async def get_statistics():
    """الحصول على الإحصائيات"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            # إجمالي المواليد
            cursor.execute("SELECT COUNT(*) as total FROM births")
            total_births = cursor.fetchone()['total']
            
            # مواليد اليوم
            today = datetime.now().date()
            cursor.execute("SELECT COUNT(*) as today FROM births WHERE DATE(created_at) = %s", (today,))
            today_births = cursor.fetchone()['today']
            
            # عدد المستشفيات الفريدة
            cursor.execute("SELECT COUNT(DISTINCT hospital_name) as hospitals FROM births")
            hospitals_count = cursor.fetchone()['hospitals']
            
            return {
                "total_births": total_births,
                "today_births": today_births,
                "hospitals_count": hospitals_count
            }
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

# تحسين دالة البحث
@app.get("/search/{search_id}")
async def search_data(search_id: str):
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
            SELECT 
                mother_name, father_full_name, hospital_name,
                DATE_FORMAT(birth_date, '%Y-%m-%d') as birth_date,
                father_id_type, mother_id_type,
                created_at
            FROM births 
            WHERE father_id = %s OR mother_id = %s
            ORDER BY created_at DESC
            """, (search_id, search_id))
            
            results = cursor.fetchall()
            if not results:
                raise HTTPException(status_code=404, detail="لم يتم العثور على نتائج")
                
            return {"results": [{
                "mother_name": r['mother_name'],
                "father_full_name": r['father_full_name'],
                "hospital_name": r['hospital_name'],
                "birth_date": r['birth_date'],
                "father_id_type": r['father_id_type'],
                "mother_id_type": r['mother_id_type']
            } for r in results]}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/delete-old-entries/")
async def delete_old_entries():
    try:
        cutoff_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM births WHERE birth_date < %s", (cutoff_date,))
            conn.commit()
            return {"message": "تم حذف السجلات القديمة بنجاح"}
    except Error as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    try:
        # اختبار الاتصال بقاعدة البيانات
        with db_manager.get_connection() as conn:
            if conn.is_connected():
                return {
                    "status": "online",
                    "message": "نظام تسجيل المواليد يعمل",
                    "database": "متصل"
                }
    except Error:
        return {
            "status": "online",
            "message": "نظام تسجيل المواليد يعمل",
            "database": "غير متصل"
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
