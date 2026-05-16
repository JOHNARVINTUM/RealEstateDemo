"""
Management command to migrate admin users from local SQLite to Supabase PostgreSQL.
Only migrates ADMIN users and deletes the local SQLite database after successful migration.
"""

import os
import sqlite3
import shutil
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()


class Command(BaseCommand):
    help = "Migrate admin users from SQLite to Supabase and delete local database"

    def handle(self, *args, **options):
        # Path to local SQLite database
        sqlite_db_path = Path(settings.BASE_DIR) / "complete_dataset.db"
        
        if not sqlite_db_path.exists():
            self.stdout.write(
                self.style.WARNING(f"SQLite database not found at {sqlite_db_path}")
            )
            self.stdout.write("No migration needed.")
            return

        self.stdout.write(f"Found SQLite database at {sqlite_db_path}")

        # Connect to SQLite database
        try:
            sqlite_conn = sqlite3.connect(str(sqlite_db_path))
            sqlite_conn.row_factory = sqlite3.Row
            sqlite_cursor = sqlite_conn.cursor()
        except Exception as e:
            raise CommandError(f"Failed to connect to SQLite database: {e}")

        # Extract admin users from SQLite
        self.stdout.write("Extracting admin users from SQLite...")
        
        sqlite_cursor.execute("""
            SELECT id, email, username, first_name, last_name, 
                   is_active, date_joined, role
            FROM auth_user 
            WHERE role = 'ADMIN'
        """)
        
        admin_rows = sqlite_cursor.fetchall()
        
        if not admin_rows:
            self.stdout.write(
                self.style.WARNING("No admin users found in SQLite database")
            )
            sqlite_conn.close()
            return

        self.stdout.write(f"Found {len(admin_rows)} admin user(s) to migrate")

        # Migrate to Supabase (PostgreSQL via Django ORM)
        migrated_count = 0
        for row in admin_rows:
            email = row['email']
            
            # Check if admin already exists in Supabase
            if User.objects.filter(email=email).exists():
                self.stdout.write(
                    self.style.WARNING(f"Admin with email {email} already exists in Supabase, skipping")
                )
                continue

            try:
                # Create admin user
                admin = User(
                    id=row['id'],
                    email=row['email'],
                    username=row['username'],
                    first_name=row['first_name'] or '',
                    last_name=row['last_name'] or '',
                    is_superuser=True,  # Admin users are superusers
                    is_staff=True,  # Admin users can access admin
                    is_active=row['is_active'],
                    role=row['role'],
                    date_joined=row['date_joined'],
                )
                # Set a default password since SQLite might not have hashed passwords
                admin.set_password('admin123')  # Default password, user should change
                admin.save()
                migrated_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Migrated admin: {email}")
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to migrate admin {email}: {e}")
                )

        sqlite_conn.close()

        # Verify migration
        self.stdout.write("\nVerifying migration...")
        admin_count = User.objects.filter(role='ADMIN').count()
        self.stdout.write(f"Total admin users in Supabase: {admin_count}")

        # Delete local SQLite database
        if migrated_count > 0:
            self.stdout.write(f"\nDeleting local SQLite database: {sqlite_db_path}")
            try:
                # Create backup first
                backup_path = sqlite_db_path.with_suffix('.db.backup')
                shutil.copy2(sqlite_db_path, backup_path)
                self.stdout.write(f"Backup created at {backup_path}")
                
                # Delete original
                sqlite_db_path.unlink()
                self.stdout.write(
                    self.style.SUCCESS("Local SQLite database deleted successfully")
                )
            except Exception as e:
                raise CommandError(f"Failed to delete SQLite database: {e}")
        else:
            self.stdout.write(
                self.style.WARNING("No new admins migrated, keeping local database")
            )

        self.stdout.write(
            self.style.SUCCESS(f"\nMigration complete. Migrated {migrated_count} admin user(s) to Supabase.")
        )
