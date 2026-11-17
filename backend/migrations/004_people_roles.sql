-- Job titles shown beside a person's manager and buddy.
alter table people add column manager_role text, add column buddy_role text;
