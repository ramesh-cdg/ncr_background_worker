"""
Database connection and operations module
"""
import pymysql
from typing import List, Tuple, Optional
from config import settings


class DatabaseManager:
    """Database connection and operations manager"""
    
    @staticmethod
    def get_connection():
        """Get database connection"""
        return pymysql.connect(
            host=settings.db_host,
            user=settings.db_user,
            password=settings.db_pass,
            db=settings.db_name
        )
    
    @staticmethod
    def get_file_paths_from_db(job_id: str) -> Tuple[List[str], str]:
        """Get file paths and SKU ID from database for a job"""
        print(f"🗄️ [DB] Getting file paths for job_id: {job_id}")
        
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get file paths
            print(f"🗄️ [DB] Executing file paths query...")
            cursor.execute(
                """
                SELECT file_path
                FROM job_files
                WHERE job_id = %s
                  AND file_type = 'base'
                  AND LOWER(file_path) NOT REGEXP '/source_.*\\.(jpg|jpeg|png|webp|avif)$'
                  AND DATE(`timestamp`) = (
                      SELECT DATE(MAX(`timestamp`))
                      FROM job_files
                      WHERE job_id = %s
                        AND file_type = 'base'
                        AND LOWER(file_path) NOT REGEXP '/source_.*\\.(jpg|jpeg|png|webp|avif)$'
                  )
                ORDER BY
                  CASE WHEN LOWER(file_path) LIKE '%%.glb' THEN 1 ELSE 0 END,
                  file_path ASC
                """,
                (job_id, job_id)
            )
            
            paths = [row[0] for row in cursor.fetchall()]
            print(f"🗄️ [DB] File paths query returned {len(paths)} results")
            
            # Get SKU ID
            print(f"🗄️ [DB] Executing SKU ID query...")
            cursor.execute(
                """
                SELECT sku_id FROM job_details WHERE job_id = %s AND status = 'Active' LIMIT 1
                """,
                (job_id,)
            )
            result = cursor.fetchone()
            sku_id = result[0] if result else None
            print(f"🗄️ [DB] SKU ID query returned: {sku_id}")
            
            return paths, sku_id
            
        except Exception as e:
            print(f"🗄️ [DB] ERROR in get_file_paths_from_db: {e}")
            raise e
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def update_job_details_for_validation(
        job_id: str, 
        sku_id: str, 
        username: str, 
        campaign: str, 
        current_datetime: str,
        row_id: Optional[int] = None
    ) -> bool:
        """Update job details after successful validation"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            if row_id:
                # Update with row_id if provided
                cursor.execute("""
                    UPDATE job_details 
                    SET `is_reviewed` = 0, `is_uploaded` = 0, `job_status` = 'IAPPROVED', 
                        upload_count = upload_count + 1, uploadTime = %s, updateTime = %s 
                    WHERE id = %s AND `is_uploaded` = 1
                """, (current_datetime, current_datetime, row_id))
            else:
                # Update without row_id (use job_id)
                cursor.execute("""
                    UPDATE job_details 
                    SET `is_reviewed` = 0, `is_uploaded` = 0, `job_status` = 'IAPPROVED', 
                        upload_count = upload_count + 1, uploadTime = %s, updateTime = %s 
                    WHERE job_id = %s AND `is_uploaded` = 1
                """, (current_datetime, current_datetime, job_id))
            
            if cursor.rowcount > 0:
                # Insert into email table
                cursor.execute("""
                    INSERT INTO `email`(`sku`, `status`, `campagin`) 
                    VALUES (%s, 'Waiting', %s)
                """, (sku_id, campaign))
                
                # Insert into history_log table
                cursor.execute("""
                    INSERT INTO `history_log`(`sku_id`, `action`, `action_by`, `timestamp`) 
                    VALUES (%s, 'review', %s, %s)
                """, (sku_id, username, current_datetime))
                
                conn.commit()
                return True
            else:
                return False
                
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def update_job_details_for_failed_validation(
        job_id: str, 
        current_datetime: str,
        row_id: Optional[int] = None
    ) -> bool:
        """Update job details after failed validation"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            if row_id:
                cursor.execute("""
                    UPDATE job_details 
                    SET `is_uploaded` = 0, updateTime = %s 
                    WHERE id = %s AND `is_uploaded` = 1
                """, (current_datetime, row_id))
            else:
                cursor.execute("""
                    UPDATE job_details 
                    SET `is_uploaded` = 0, updateTime = %s 
                    WHERE job_id = %s AND `is_uploaded` = 1
                """, (current_datetime, job_id))
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def save_validation_response(job_id: str, response_status: int, response_json: str):
        """Save validation response to database"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                INSERT INTO model_validation (job_id, response, json) VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE response = VALUES(response), json = VALUES(json)
                """, 
                (job_id, response_status, response_json)
            )
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def save_validation_failed_request(
        job_id: str, 
        sku_id: str, 
        response: str, 
        api_url: str, 
        username: str, 
        campaign: str, 
        row_id: Optional[int] = None
    ):
        """Save failed validation request to validation_failed_req table"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                INSERT INTO validation_failed_req 
                (job_id, sku_id, response, api_url, username, campaign, row_id, timestamp) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """, 
                (job_id, sku_id, response, api_url, username, campaign, row_id)
            )
            conn.commit()
            print(f"🗄️ [DB] Failed validation request logged to validation_failed_req table")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ [DB] Error saving failed validation request: {e}")
            # Don't raise the exception to avoid breaking the main flow
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def update_job_files_table(job_id: str, file_path: str, timestamp: str):
        """Update or insert file path in job_files table"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            # Check if file_path exists
            cursor.execute("SELECT id FROM job_files WHERE file_path = %s AND file_type = 'base'", (file_path,))
            
            if cursor.fetchone():
                # Update timestamp if exists
                cursor.execute("UPDATE job_files SET timestamp = %s WHERE file_path = %s AND file_type = 'base'", (timestamp, file_path))
            else:
                # Insert new entry
                cursor.execute("INSERT INTO job_files (job_id, file_path, file_type, timestamp) VALUES (%s, %s, 'base', %s)", (job_id, file_path, timestamp))
            
            conn.commit()
            
        except Exception as e:
            conn.rollback()
            print(f"❌ [DB] Error updating job_files table: {e}")
            # Don't raise the exception to avoid breaking the main flow
        finally:
            cursor.close()
            conn.close()
    
    @staticmethod
    def update_job_details_for_file_upload(
        job_id: str, 
        sku_id: str, 
        upload_count: int, 
        campaign: str, 
        usdz_path: str, 
        glb_path: str, 
        current_datetime: str,
        row_id: Optional[int] = None
    ) -> bool:
        """Update job details after successful file upload"""
        conn = DatabaseManager.get_connection()
        cursor = conn.cursor()
        
        try:
            # Insert into file_upload_reports table
            cursor.execute("""
                INSERT INTO file_upload_reports 
                (job_id, sku_id, upload_count, campagin, file_status, QC_status, delivery_path, glb_path, timestamp, last_update) 
                VALUES (%s, %s, %s, %s, 'IAPPROVED', 'INTERNAL', %s, %s, %s, %s)
            """, (job_id, sku_id, upload_count, campaign, usdz_path, glb_path, current_datetime, current_datetime))
            
            # Insert into email table
            cursor.execute("""
                INSERT INTO email (sku, status, campagin) 
                VALUES (%s, 'Waiting', %s)
            """, (sku_id, campaign))
            
            # Insert into history_log table
            cursor.execute("""
                INSERT INTO history_log (sku_id, action, action_by, timestamp) 
                VALUES (%s, 'review', %s, %s)
            """, (sku_id, 'system', current_datetime))
            
            # Update job_details table
            if row_id:
                cursor.execute("""
                    UPDATE job_details 
                    SET job_status = 'IAPPROVED', uploadTime = %s, updateTime = %s 
                    WHERE id = %s
                """, (current_datetime, current_datetime, row_id))
            else:
                cursor.execute("""
                    UPDATE job_details 
                    SET job_status = 'IAPPROVED', uploadTime = %s, updateTime = %s 
                    WHERE job_id = %s
                """, (current_datetime, current_datetime, job_id))
            
            conn.commit()
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"❌ [DB] Error updating job details for file upload: {e}")
            return False
        finally:
            cursor.close()
            conn.close()