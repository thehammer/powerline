_log = []
_g = {}
_window = 0
_mode = 'n'
_buf_purge_events = set()
_options = {
		'paste': 0,
		}
_last_bufnr = 0
_highlights = {}

buffers = {}

windows = []


def _buffer():
	return windows[_window - 1].buffer.number


def _logged(func):
	from functools import wraps

	@wraps(func)
	def f(*args, **kwargs):
		_log.append((func.__name__, args))
		return func(*args, **kwargs)

	return f


def _log_print():
	import sys
	for entry in _log:
		sys.stdout.write(repr(entry) + '\n')


@_logged
def command(cmd):
	if cmd.startswith('let g:'):
		import re
		varname, value = re.compile(r'^let g:(\w+)\s*=\s*(.*)').match(cmd).groups()
		_g[varname] = value
	elif cmd.startswith('hi '):
		sp = cmd.split()
		_highlights[sp[1]] = sp[2:]
	else:
		raise NotImplementedError


@_logged
def eval(expr):
	if expr.startswith('g:'):
		return _g[expr[2:]]
	elif expr.startswith('&'):
		return _options[expr[1:]]
	elif expr.startswith('PowerlineRegisterCachePurgerEvent'):
		_buf_purge_events.add(expr[expr.find('"') + 1:expr.rfind('"') - 1])
		return "0"
	raise NotImplementedError


@_logged
def bindeval(expr):
	if expr == 'g:':
		return _g
	import re
	match = re.compile(r'^function\("([^"\\]+)"\)$').match(expr)
	if match:
		return globals()['_emul_' + match.group(1)]
	else:
		raise NotImplementedError


@_logged
def _emul_mode(*args):
	if args and args[0]:
		return _mode
	else:
		return _mode[0]


@_logged
def _emul_getbufvar(bufnr, varname):
	if varname[0] == '&':
		if bufnr not in _buf_options:
			return ''
		try:
			return _buf_options[bufnr][varname[1:]]
		except KeyError:
			try:
				return _options[varname[1:]]
			except KeyError:
				return ''
	raise NotImplementedError


@_logged
def _emul_getwinvar(winnr, varname):
	return _win_scopes[winnr][varname]


@_logged
def _emul_setwinvar(winnr, varname, value):
	_win_scopes[winnr][varname] = value


@_logged
def _emul_virtcol(expr):
	if expr == '.':
		return windows[_window - 1].cursor[1] + 1
	raise NotImplementedError


@_logged
def _emul_fnamemodify(path, modstring):
	import os
	_modifiers = {
		'~': lambda path: path.replace(os.environ['HOME'], '~') if path.startswith(os.environ['HOME']) else path,
		'.': lambda path: (lambda tpath: path if tpath[:3] == '..' + os.sep else tpath)(os.path.relpath(path)),
		't': lambda path: os.path.basename(path),
		'h': lambda path: os.path.dirname(path),
	}

	for mods in modstring.split(':')[1:]:
		path = _modifiers[mods](path)
	return path


@_logged
def _emul_expand(expr):
	if expr == '<abuf>':
		return _buffer()
	raise NotImplementedError


@_logged
def _emul_bufnr(expr):
	if expr == '$':
		return _last_bufnr
	raise NotImplementedError


@_logged
def _emul_exists(varname):
	if varname.startswith('g:'):
		return varname[2:] in _g
	raise NotImplementedError


_window_ids = [None]
_window_id = 0
_win_scopes = [None]
_win_options = [None]


class _Window(object):
	def __init__(self, buffer=None, cursor=(1, 0), width=80):
		global _window_id
		self.cursor = cursor
		self.width = width
		if buffer:
			if type(buffer) is _Buffer:
				self.buffer = buffer
			else:
				self.buffer = _Buffer(**buffer)
		else:
			self.buffer = _Buffer()
		windows.append(self)
		_window_id += 1
		_window_ids.append(_window_id)
		_win_scopes.append({})
		_win_options.append({})

	def __repr__(self):
		return '<window ' + str(windows.index(self)) + '>'


_buf_scopes = {}
_buf_options = {}
_buf_lines = {}
_undostate = {}
_undo_written = {}


class _Buffer(object):
	def __init__(self, name=None):
		global _last_bufnr
		import os
		_last_bufnr += 1
		bufnr = _last_bufnr
		self.number = bufnr
		self.name = os.path.abspath(name) if name else None
		_buf_scopes[bufnr] = {}
		_buf_options[bufnr] = {
				'modified': 0,
				'readonly': 0,
				'fileformat': 'unix',
				'filetype': '',
				'buftype': '',
				'fileencoding': 'utf-8',
				}
		_buf_lines[bufnr] = ['']
		from copy import copy
		_undostate[bufnr] = [copy(_buf_lines[bufnr])]
		_undo_written[bufnr] = len(_undostate[bufnr])
		buffers[bufnr] = self

	def __getitem__(self, line):
		return _buf_lines[self.number][line]

	def __setitem__(self, line, value):
		_buf_options[self.number]['modified'] = 1
		_buf_lines[self.number][line] = value
		from copy import copy
		_undostate[self.number].append(copy(_buf_lines[self.number]))

	def __setslice__(self, *args):
		_buf_options[self.number]['modified'] = 1
		_buf_lines[self.number].__setslice__(*args)
		from copy import copy
		_undostate[self.number].append(copy(_buf_lines[self.number]))

	def __getslice__(self, *args):
		return _buf_lines[self.number].__getslice__(*args)

	def __len__(self):
		return len(_buf_lines[self.number])

	def __repr__(self):
		return '<buffer ' + str(self.name) + '>'

	def __del__(self):
		bufnr = self.number
		if _buf_options:
			_buf_options.pop(bufnr)
			_buf_lines.pop(bufnr)
			_undostate.pop(bufnr)
			_undo_written.pop(bufnr)
			_buf_scopes.pop(bufnr)


_dict = None


@_logged
def _init():
	global _dict

	if _dict:
		return _dict

	_dict = {}
	for varname, value in globals().items():
		if varname[0] != '_':
			_dict[varname] = value
	_new()
	return _dict


@_logged
def _get_segment_info():
	mode_translations = {
			chr(ord('V') - 0x40): '^V',
			chr(ord('S') - 0x40): '^S',
			}
	mode = _mode
	mode = mode_translations.get(mode, mode)
	return {
		'window': windows[_window - 1],
		'buffer': buffers[_buffer()],
		'bufnr': _buffer(),
		'window_id': _window_ids[_window],
		'mode': mode,
	}


@_logged
def _launch_event(event):
	pass


@_logged
def _start_mode(mode):
	global _mode
	if mode == 'i':
		_launch_event('InsertEnter')
	elif _mode == 'i':
		_launch_event('InsertLeave')
	_mode = mode


@_logged
def _undo():
	if len(_undostate[_buffer()]) == 1:
		return
	_undostate[_buffer()].pop(-1)
	_buf_lines[_buffer()] = _undostate[_buffer()][-1]
	if _undo_written[_buffer()] == len(_undostate[_buffer()]):
		_buf_options[_buffer()]['modified'] = 0


@_logged
def _edit(name=None):
	global _last_bufnr
	if _buffer() and buffers[_buffer()].name is None:
		buf = buffers[_buffer()]
		buf.name = name
	else:
		buf = _Buffer(name)
		windows[_window - 1].buffer = buf


@_logged
def _new(name=None):
	global _window
	_Window(buffer={'name': name})
	_window = len(windows)


@_logged
def _del_window(winnr):
	win = windows.pop(winnr - 1)
	_win_scopes.pop(winnr)
	_win_options.pop(winnr)
	_window_ids.pop(winnr)
	return win


@_logged
def _close(winnr, wipe=True):
	global _window
	win = _del_window(winnr)
	if _window == winnr:
		_window = len(windows)
	if wipe:
		for w in windows:
			if w.buffer.number == win.buffer.number:
				break
		else:
			_bw(win.buffer.number)
	if not windows:
		_Window()


@_logged
def _bw(bufnr=None):
	bufnr = bufnr or _buffer()
	winnr = 1
	for win in windows:
		if win.buffer.number == bufnr:
			_close(winnr, wipe=False)
		winnr += 1
	buffers.pop(bufnr)
	if not buffers:
		_Buffer()
	_b(max(buffers.keys()))


@_logged
def _b(bufnr):
	windows[_window - 1].buffer = buffers[bufnr]


@_logged
def _set_cursor(line, col):
	windows[_window - 1].cursor = (line, col)
	if _mode == 'n':
		_launch_event('CursorMoved')
	elif _mode == 'i':
		_launch_event('CursorMovedI')


@_logged
def _get_buffer():
	return buffers[_buffer()]


@_logged
def _set_bufoption(option, value, bufnr=None):
	_buf_options[bufnr or _buffer()][option] = value
	if option == 'filetype':
		_launch_event('FileType')


class _WithNewBuffer(object):
	def __init__(self, func, *args, **kwargs):
		self.call = lambda: func(*args, **kwargs)

	def __enter__(self):
		self.call()
		self.bufnr = _buffer()
		return _get_segment_info()

	def __exit__(self, *args):
		_bw(self.bufnr)


@_logged
def _set_dict(d, new, setfunc=None):
	if not setfunc:
		def setfunc(k, v):
			d[k] = v

	old = {}
	na = []
	for k, v in new.items():
		try:
			old[k] = d[k]
		except KeyError:
			na.append(k)
		setfunc(k, v)
	return old, na


class _WithBufOption(object):
	def __init__(self, **new):
		self.new = new

	def __enter__(self):
		self.bufnr = _buffer()
		self.old = _set_dict(_buf_options[self.bufnr], self.new, _set_bufoption)[0]

	def __exit__(self, *args):
		_buf_options[self.bufnr].update(self.old)


class _WithMode(object):
	def __init__(self, new):
		self.new = new

	def __enter__(self):
		self.old = _mode
		_start_mode(self.new)
		return _get_segment_info()

	def __exit__(self, *args):
		_start_mode(self.old)


class _WithDict(object):
	def __init__(self, d, **new):
		self.new = new
		self.d = d

	def __enter__(self):
		self.old, self.na = _set_dict(self.d, self.new)

	def __exit__(self, *args):
		self.d.update(self.old)
		for k in self.na:
			self.d.pop(k)


@_logged
def _with(key, *args, **kwargs):
	if key == 'buffer':
		return _WithNewBuffer(_edit, *args, **kwargs)
	elif key == 'mode':
		return _WithMode(*args, **kwargs)
	elif key == 'bufoptions':
		return _WithBufOption(**kwargs)
	elif key == 'options':
		return _WithDict(_options, **kwargs)
	elif key == 'globals':
		return _WithDict(_g, **kwargs)
