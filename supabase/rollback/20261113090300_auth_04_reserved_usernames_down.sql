-- Rollback for 20261113090300_auth_04_reserved_usernames.sql
-- Removes only the handles seeded by the forward migration. Rows added later
-- by a human are left in place: a rollback must not discard real decisions.

delete from public.reserved_usernames
 where name in (
    'admin', 'administrator', 'root', 'sysadmin', 'system', 'support', 'help',
    'helpdesk', 'staff', 'moderator', 'mod', 'official', 'security', 'billing',
    'sales', 'api', 'www', 'mail', 'ftp', 'null', 'undefined', 'anonymous',
    'guest', 'user', 'test', 'demo', 'trilingual', 'dictionary', 'nepali',
    'ceo', 'founder'
 );
