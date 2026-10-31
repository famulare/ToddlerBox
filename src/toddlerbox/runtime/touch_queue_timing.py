"""Optional SDL2 queue residence sampling, never physical touch latency.

Only the verified Linux x86-64 pygame/SDL ABI is supported. No filter, callback,
grab, injection, consumption or event payload is retained. Unsupported builds
simply omit this diagnostic. Loaded only after root explicitly arms Paint timing.
"""
import ctypes
import platform


class _Event(ctypes.Union):
    _fields_ = [('header', ctypes.c_uint32 * 2),
                ('padding', ctypes.c_ubyte * 56), ('alignment', ctypes.c_uint64)]


class TouchQueueTiming:
    def __init__(self, sdl):
        self.sdl = sdl
        self.events = (_Event * 64)()
        sdl.SDL_PeepEvents.argtypes = [ctypes.POINTER(_Event), ctypes.c_int,
                                     ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32]
        sdl.SDL_PeepEvents.restype = ctypes.c_int
        sdl.SDL_GetTicks.argtypes = []
        sdl.SDL_GetTicks.restype = ctypes.c_uint32

    @classmethod
    def available(cls):
        import pygame
        if (platform.system(), platform.machine(), pygame.version.ver,
                pygame.get_sdl_version(), ctypes.sizeof(_Event)) != (
                'Linux', 'x86_64', '2.5.8', (2, 32, 10), 56):
            return None
        try:
            # Resolve symbols through pygame's loaded extension, not a second SDL.
            return cls(ctypes.CDLL(pygame.base.__file__))
        except (OSError, AttributeError):
            return None

    def sample(self):
        # SDL_PEEKEVENT=1; only SDL_FINGERDOWN/UP/MOTION (0x700..0x702).
        count = self.sdl.SDL_PeepEvents(self.events, 64, 1, 0x700, 0x702)
        if count < 0:
            return None
        now = self.sdl.SDL_GetTicks()
        ages = []
        for index in range(min(count, 64)):
            stamp = self.events[index].header[1]
            age = (now - stamp) & 0xffffffff
            # SDL_PushEvent stamps with SDL_GetTicks. Bound/wrap-check before
            # interpreting; zero/future/mismatched timestamps are omitted.
            if stamp and age < 600_000:
                ages.append(age / 1000.)
        ctypes.memset(self.events, 0, ctypes.sizeof(self.events))
        return count, ages
