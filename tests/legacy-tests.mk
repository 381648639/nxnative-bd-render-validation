t_bd_legacy_replay: t_bd_legacy_replay.m $(MTL_T_DEP)
	clang $(CFLAGS) -fobjc-arc -o $@ t_bd_legacy_replay.m $(MTL_T_SRC) $(FW)

t_legacy_null_diagnostics: t_legacy_null_diagnostics.m $(MTL_T_DEP)
	clang $(CFLAGS) -fobjc-arc -o $@ t_legacy_null_diagnostics.m $(MTL_T_SRC) $(FW)
