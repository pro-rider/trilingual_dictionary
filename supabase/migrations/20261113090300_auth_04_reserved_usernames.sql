-- ============================================================================
-- Auth system — migration 4 of 4: reserved handles.
--
-- Compared case-insensitively by the backend (`lower(username) = name`). The
-- list is deliberately blunt: brand, impersonation and staff-sounding names,
-- plus a few technical strings that make routing or UI copy confusing.
-- Extend with your own support/brand names before launch.
-- ============================================================================

insert into public.reserved_usernames (name, reason) values
    ('admin',        'staff'),
    ('administrator','staff'),
    ('root',         'staff'),
    ('sysadmin',     'staff'),
    ('system',       'staff'),
    ('support',      'staff'),
    ('help',         'staff'),
    ('helpdesk',     'staff'),
    ('staff',        'staff'),
    ('moderator',    'staff'),
    ('mod',          'staff'),
    ('official',     'impersonation'),
    ('security',     'staff'),
    ('billing',      'staff'),
    ('sales',        'impersonation'),
    ('api',          'technical'),
    ('www',          'technical'),
    ('mail',         'technical'),
    ('ftp',          'technical'),
    ('null',         'technical'),
    ('undefined',    'technical'),
    ('anonymous',    'technical'),
    ('guest',        'technical'),
    ('user',         'technical'),
    ('test',         'technical'),
    ('demo',         'technical'),
    ('trilingual',   'brand'),
    ('dictionary',   'brand'),
    ('nepali',       'brand'),
    ('ceo',          'impersonation'),
    ('founder',      'impersonation')
on conflict (name) do nothing;
