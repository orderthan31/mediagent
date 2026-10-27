-- Lock-only application capability. Do not grant control-group mutation to dispatchers.
DO $outer$
DECLARE ns text:=current_schema();
BEGIN
 EXECUTE format(
  'CREATE FUNCTION %I.managed_dispatch_group(p_agent text) RETURNS SETOF %I.remote_control_groups LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS %L',
  ns,ns,format('SELECT * FROM %I.remote_control_groups WHERE agent_id=p_agent FOR SHARE',ns)
 );
 EXECUTE format('REVOKE ALL ON FUNCTION %I.managed_dispatch_group(text) FROM PUBLIC',ns);
END;
$outer$;
