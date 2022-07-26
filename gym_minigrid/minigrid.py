# MODIFIED FROM MINIGRID REPO

import hashlib
import gym
from enum import IntEnum
from gym import spaces
from gym.utils import seeding
from .objects import _OBJECT_CLASS, _OBJECT_COLOR
from .globals import COLOR_NAMES
from .objects import *
from .bddl import _ALL_ACTIONS
from .agent import Agent

# Size in pixels of a tile in the full-scale human view
TILE_PIXELS = 32


class Grid:
    """
    Represent a grid and operations on it
    """

    # Static cache of pre-renderer tiles
    tile_cache = {}

    def __init__(self, width, height):
        assert width >= 3
        assert height >= 3

        self.width = width
        self.height = height

        self.grid = [None] * width * height

    def __contains__(self, key):
        if isinstance(key, WorldObj):
            for e in self.grid:
                if e is key:
                    return True
        elif isinstance(key, tuple):
            for e in self.grid:
                if e is None:
                    continue
                if (e.color, e.type) == key:
                    return True
                if key[0] is None and key[1] == e.type:
                    return True
        return False

    def __eq__(self, other):
        grid1 = self.encode()
        grid2 = other.encode()
        return np.array_equal(grid2, grid1)

    def __ne__(self, other):
        return not self == other

    def copy(self):
        from copy import deepcopy
        return deepcopy(self)

    def set(self, i, j, v):
        assert 0 <= i < self.width
        assert 0 <= j < self.height
        if v is None or self.grid[j * self.width + i] is None:
            self.grid[j * self.width + i] = v
        elif isinstance(self.grid[j * self.width + i], list):
            self.grid[j * self.width + i].append(v)
        else:
            self.grid[j * self.width + i] = [self.grid[j * self.width + i], v]

    def remove(self, i, j, v):
        assert 0 <= i < self.width
        assert 0 <= j < self.height
        cur_objs = self.grid[j * self.width + i]
        if cur_objs:
            if isinstance(cur_objs, list):
                if len(cur_objs) == 1:
                    self.grid[j * self.width + i] = None
                else:
                    self.grid[j * self.width + i].remove(v)
            else:
                self.grid[j * self.width + i] = None

    def get(self, i, j):
        assert 0 <= i < self.width
        assert 0 <= j < self.height
        return self.grid[j * self.width + i]

    def horz_wall(self, x, y, length=None, obj_type=Wall):
        if length is None:
            length = self.width - x
        for i in range(0, length):
            self.set(x + i, y, obj_type())

    def vert_wall(self, x, y, length=None, obj_type=Wall):
        if length is None:
            length = self.height - y
        for j in range(0, length):
            self.set(x, y + j, obj_type())

    def wall_rect(self, x, y, w, h):
        self.horz_wall(x, y, w)
        self.horz_wall(x, y+h-1, w)
        self.vert_wall(x, y, h)
        self.vert_wall(x+w-1, y, h)

    def rotate_left(self):
        """
        Rotate the grid to the left (counter-clockwise)
        """

        grid = Grid(self.height, self.width)

        for i in range(self.width):
            for j in range(self.height):
                v = self.get(i, j)
                grid.set(j, grid.height - 1 - i, v)

        return grid

    def slice(self, topX, topY, width, height):
        """
        Get a subset of the grid
        """

        grid = Grid(width, height)

        for j in range(0, height):
            for i in range(0, width):
                x = topX + i
                y = topY + j

                if 0 <= x < self.width and 0 <= y < self.height:
                    v = self.get(x, y)
                else:
                    v = Wall()

                grid.set(i, j, v)

        return grid

    @classmethod
    def render_tile(
        cls,
        objs,
        agent_dir=None,
        highlight=False,
        tile_size=TILE_PIXELS,
        subdivs=3,
    ):
        """
        Render a tile and cache the result
        """

        # Hash map lookup key for the cache
        key = (agent_dir, highlight, tile_size)

        if isinstance(objs, list):
            keys = [obj.encode() for obj in objs if obj is not None]
            key = tuple(keys) + key
        elif objs:
            key = objs.encode() + key

        if key in cls.tile_cache:
            return cls.tile_cache[key]

        img = np.zeros(shape=(tile_size * subdivs, tile_size * subdivs, 3), dtype=np.uint8)

        # Draw the grid lines (top and left edges)
        fill_coords(img, point_in_rect(0, 0.031, 0, 1), (100, 100, 100))
        fill_coords(img, point_in_rect(0, 1, 0, 0.031), (100, 100, 100))

        if isinstance(objs, list):
            for obj in objs:
                obj.render(img)
        elif objs:
            objs.render(img)

        # Overlay the agent on top
        if agent_dir is not None:
            tri_fn = point_in_triangle(
                (0.12, 0.19),
                (0.87, 0.50),
                (0.12, 0.81),
            )

            # Rotate the agent based on its direction
            tri_fn = rotate_fn(tri_fn, cx=0.5, cy=0.5, theta=0.5*math.pi*agent_dir)
            fill_coords(img, tri_fn, (255, 0, 0))

        # Highlight the cell if needed
        if highlight:
            highlight_img(img)

        # Downsample the image to perform supersampling/anti-aliasing
        img = downsample(img, subdivs)

        # Cache the rendered tile
        cls.tile_cache[key] = img

        return img

    def render(
        self,
        tile_size,
        agent_pos=None,
        agent_dir=None,
        highlight_mask=None
    ):
        """
        Render this grid at a given scale
        :param r: target renderer object
        :param tile_size: tile size in pixels
        """

        if highlight_mask is None:
            highlight_mask = np.zeros(shape=(self.width, self.height), dtype=bool)

        # Compute the total grid size
        width_px = self.width * tile_size
        height_px = self.height * tile_size

        img = np.zeros(shape=(height_px, width_px, 3), dtype=np.uint8)

        # Render the grid
        for j in range(0, self.height):
            for i in range(0, self.width):
                cell = self.get(i, j)

                agent_here = np.array_equal(agent_pos, (i, j))
                tile_img = Grid.render_tile(
                    cell,
                    agent_dir=agent_dir if agent_here else None,
                    highlight=highlight_mask[i, j],
                    tile_size=tile_size,
                )

                ymin = j * tile_size
                ymax = (j+1) * tile_size
                xmin = i * tile_size
                xmax = (i+1) * tile_size
                img[ymin:ymax, xmin:xmax, :] = tile_img

        return img

    def encode(self, vis_mask=None):
        """
        Produce a compact numpy encoding of the grid
        """

        if vis_mask is None:
            vis_mask = np.ones((self.width, self.height), dtype=bool)

        array = np.zeros((self.width, self.height, 3), dtype='uint8')

        for i in range(self.width):
            for j in range(self.height):
                if vis_mask[i, j]:
                    v = self.get(i, j)

                    if v is None:
                        array[i, j, 0] = OBJECT_TO_IDX['empty']
                        array[i, j, 1] = 0
                        array[i, j, 2] = 0
                    # else:
                    #     array[i, j, :] = v.encode()
                    elif isinstance(v, list):
                        for obj in v:
                            array[i, j, :] = np.add(array[i, j, :], obj.encode())
                    elif not isinstance(v, list):
                        array[i, j, :] = v.encode()

        return array

    @staticmethod
    def decode(array):
        """
        Decode an array grid encoding back into a grid
        """

        width, height, channels = array.shape
        assert channels == 3

        vis_mask = np.ones(shape=(width, height), dtype=bool)

        grid = Grid(width, height)
        for i in range(width):
            for j in range(height):
                type_idx, color_idx, state = array[i, j]
                v = WorldObj.decode(type_idx, color_idx, state)
                grid.set(i, j, v)
                vis_mask[i, j] = (type_idx != OBJECT_TO_IDX['unseen'])

        return grid, vis_mask

    def process_vis(grid, agent_pos):
        # agent_pos=(self.agent.view_size // 2 , self.agent.view_size - 1)
        mask = np.zeros(shape=(grid.width, grid.height), dtype=bool)

        mask[agent_pos[0], agent_pos[1]] = True

        for j in reversed(range(0, grid.height)):
            for i in range(0, grid.width-1):
                if not mask[i, j]:
                    continue

                cell = grid.get(i, j)

                if isinstance(cell, list):
                    for obj in cell:
                        if obj and not obj.can_seebehind:
                            break
                    break
                else:
                    if cell and not cell.can_seebehind:
                        break

                mask[i+1, j] = True
                if j > 0:
                    mask[i+1, j-1] = True
                    mask[i, j-1] = True

            for i in reversed(range(1, grid.width)):
                if not mask[i, j]:
                    continue

                cell = grid.get(i, j)
                # if cell and not cell.see_behind():
                if isinstance(cell, list):
                    for obj in cell:
                        if obj and not obj.can_seebehind:
                            break
                    break
                else:
                    if cell and not cell.can_seebehind:
                        break

                mask[i-1, j] = True
                if j > 0:
                    mask[i-1, j-1] = True
                    mask[i, j-1] = True

        for j in range(0, grid.height):
            for i in range(0, grid.width):
                if not mask[i, j]:
                    grid.set(i, j, None)

        return mask


class MiniGridEnv(gym.Env):
    """
    2D grid world game environment
    """

    metadata = {
        'render.modes': ['human', 'rgb_array'],
        'video.frames_per_second': 10
    }

    def __init__(
        self,
        mode='not_human',
        grid_size=None,
        width=None,
        height=None,
        num_objs=None,
        max_steps=1e5,
        see_through_walls=False,
        seed=1337,
        agent_view_size=7,
    ):
        # Can't set both grid_size and width/height
        self.episode = 0

        if grid_size:
            assert width is None and height is None
            width = grid_size
            height = grid_size

        self.mode = mode
        self.last_action = None
        self.action_done = None

        if num_objs is None:
            num_objs = {}
        self.num_objs = num_objs

        # TODO: get rid of self.objs
        self.objs = {}
        self.obj_instances = {}
        for obj in num_objs.keys():
            self.objs[obj] = []
            for i in range(num_objs[obj]):
                obj_name = '{}_{}'.format(obj, i)
                obj_instance = _OBJECT_CLASS[obj](_OBJECT_COLOR[obj], obj_name)
                self.objs[obj].append(obj_instance)
                self.obj_instances[obj_name] = obj_instance

        self.doors = []
        # Action enumeration for this environment
        self.actions()

        # Actions are discrete integer values
        self.action_space = spaces.Discrete(len(self.actions))

        # Number of cells (width and height) in the agent view
        assert agent_view_size % 2 == 1
        assert agent_view_size >= 3

        # initialize agent
        self.agent = Agent(self, agent_view_size)

        # Observations are dictionaries containing an
        # encoding of the grid and a textual 'mission' string
        self.observation_space = spaces.Box(
            low=0,
            high=255,
            shape=(self.agent.view_size, self.agent.view_size, 3),
            dtype='uint8'
        )
        self.observation_space = spaces.Dict({
            'image': self.observation_space
        })

        # Range of possible rewards
        self.reward_range = (0, math.inf)

        # Window to use for human rendering mode
        self.window = None

        # Environment configuration
        self.width = width
        self.height = height
        self.max_steps = max_steps
        self.see_through_walls = see_through_walls

        # Initialize the RNG
        self.seed(seed=seed)

        # Initialize the state
        self.reset()

        self.mission = ''

    def actions(self):
        # creates Actions class
        actions = {'left': 0,
                   'right': 1,
                   'forward': 2}
                   # 'done': 3}

        i = 3
        for objs in self.objs.values():
            for obj in objs:
                for action in _ALL_ACTIONS:
                    if obj.possible_action(action):
                        obj_action = '{}/{}'.format(obj.name, action)
                        actions[obj_action] = i
                        i += 1

        self.actions = IntEnum('Actions', actions)

    def reset(self):
        # Current position and direction of the agent
        self.agent.reset()

        for obj in self.obj_instances.values():
            obj.reset()

        self.reward = 0
        self.doors = []

        # Generate a new random grid at the start of each episode
        # To keep the same grid for each episode, call env.seed() with
        # the same seed before calling env.reset()
        self._gen_grid(self.width, self.height)

        # These fields should be defined by _gen_grid
        assert self.agent.cur_pos is not None
        assert self.agent.dir is not None

        # Check that the agent doesn't overlap with an object
        start_cell = self.grid.get(*self.agent.cur_pos)

        can_overlap = True
        if start_cell is not None:
            if not isinstance(start_cell, list):
                start_cell = [start_cell]
            for obj in start_cell:
                if not obj.can_overlap:
                    can_overlap = False

        assert start_cell is None or can_overlap is True

        # Step count since episode start
        self.step_count = 0
        self.episode += 1

        # Return first observation
        obs = self.gen_obs()
        return obs

    def seed(self, seed=1337):
        # Seed the random number generator
        self.np_random, _ = seeding.np_random(seed)
        return [seed]

    def hash(self, size=16):
        """Compute a hash that uniquely identifies the current state of the environment.
        :param size: Size of the hashing
        """
        sample_hash = hashlib.sha256()

        to_encode = [self.grid.encode().tolist(), self.agent.cur_pos, self.agent.dir]
        for item in to_encode:
            sample_hash.update(str(item).encode('utf8'))

        return sample_hash.hexdigest()[:size]

    @property
    def steps_remaining(self):
        return self.max_steps - self.step_count

    def __str__(self):
        """
        Produce a pretty string of the environment's grid along with the agent.
        A grid cell is represented by seed 0_2-character string, the first one for
        the object and the second one for the color.
        """

        # Map of object types to short string
        OBJECT_TO_STR = {
            'wall'          : 'W',
            'floor'         : 'F',
            'door'          : 'D',
            'key'           : 'K',
            'ball'          : 'A',
            'box'           : 'B',
            'goal'          : 'G',
            'lava'          : 'V',
            'counter'       : 'C',
            's_ball'        : 'S'
        }

        # Short string for opened door
        OPENDED_DOOR_IDS = '_'

        # Map agent's direction to short string
        AGENT_DIR_TO_STR = {
            0: '>',
            1: 'V',
            2: '<',
            3: '^'
        }

        str = ''

        for j in range(self.grid.height):
            for i in range(self.grid.width):
                if i == self.agent.cur_pos[0] and j == self.agent.cur_pos[1]:
                    str += 2 * AGENT_DIR_TO_STR[self.agent.dir]
                    continue

                c = self.grid.get(i, j)

                if c is None:
                    str += '  '
                    continue

                if c.type == 'door':
                    if c.is_open:
                        str += '__'
                    elif c.is_locked:
                        str += 'L' + c.color[0].upper()
                    else:
                        str += 'D' + c.color[0].upper()
                    continue

                str += OBJECT_TO_STR[c.type] + c.color[0].upper()

            if j < self.grid.height - 1:
                str += '\n'

        return str

    def _gen_grid(self, width, height):
        self.grid = Grid(width, height)
        self._gen_objs()
        assert self._init_conditions(), "Does not satisfy initial conditions"
        self.place_agent()
        self.mission = self.mission

    def _gen_objs(self):
        assert False, "_gen_objs needs to be implemented by each environment"

    def _reward(self):
        """
        Compute the reward to be given upon success
        """
        assert False, "_reward needs to be implemented by each environment"
        # return 1 - 0.9 * (self.step_count / self.max_steps)

    def _init_conditions(self):
        print('no init conditions')
        return True

    def _end_conditions(self):
        assert False, "_end_conditions needs to be implemented by each environment"

    def _rand_int(self, low, high):
        """
        Generate random integer in [low,high[
        """

        return self.np_random.randint(low, high)

    def _rand_float(self, low, high):
        """
        Generate random float in [low,high[
        """

        return self.np_random.uniform(low, high)

    def _rand_bool(self):
        """
        Generate random boolean value
        """

        return self.np_random.randint(0, 2) == 0

    def _rand_elem(self, iterable):
        """
        Pick a random element in a list
        """

        lst = list(iterable)
        idx = self._rand_int(0, len(lst))
        return lst[idx]

    def _rand_subset(self, iterable, num_elems):
        """
        Sample a random subset of distinct elements of a list
        """

        lst = list(iterable)
        assert num_elems <= len(lst)

        out = []

        while len(out) < num_elems:
            elem = self._rand_elem(lst)
            lst.remove(elem)
            out.append(elem)

        return out

    def _rand_color(self):
        """
        Generate a random color name (string)
        """

        return self._rand_elem(COLOR_NAMES)

    def _rand_pos(self, xLow, xHigh, yLow, yHigh):
        """
        Generate a random (x,y) position tuple
        """

        return (
            self.np_random.randint(xLow, xHigh),
            self.np_random.randint(yLow, yHigh)
        )

    def place_obj(self,
                  obj,
                  top=None,
                  size=None,
                  reject_fn=None,
                  max_tries=math.inf
    ):
        """
        Place an object at an empty position in the grid

        :param top: top-left position of the rectangle where to place
        :param size: size of the rectangle where to place
        :param reject_fn: function to filter out potential positions
        """

        if top is None:
            top = (0, 0)
        else:
            top = (max(top[0], 0), max(top[1], 0))

        if size is None:
            size = (self.grid.width, self.grid.height)

        num_tries = 0

        while True:
            # This is to handle with rare cases where rejection sampling
            # gets stuck in an infinite loop
            if num_tries > max_tries:
                raise RecursionError('rejection sampling failed in place_obj')

            num_tries += 1

            pos = np.array((
                self._rand_int(top[0], min(top[0] + size[0], self.grid.width)),
                self._rand_int(top[1], min(top[1] + size[1], self.grid.height))
            ))

            # Don't place the object on top of another object
            if self.grid.get(*pos) is not None:
                continue

            # Don't place the object where the agent is
            if np.array_equal(pos, self.agent.cur_pos):
                continue

            # Check if there is a filtering criterion
            if reject_fn and reject_fn(self, pos):
                continue

            break

        self.grid.set(*pos, obj)

        if obj is not None:
            obj.init_pos = pos
            obj.cur_pos = pos

        return pos

    def put_obj(self, obj, i, j):
        """
        Put an object at a specific position in the grid
        """

        self.grid.set(i, j, obj)
        obj.init_pos = (i, j)
        obj.cur_pos = (i, j)

    def place_agent(
        self,
        top=None,
        size=None,
        rand_dir=True,
        max_tries=math.inf
    ):
        """
        Set the agent's starting point at an empty position in the grid
        """

        self.agent.cur_pos = None

        next_to = True
        while next_to:
            pos = self.place_obj(None, top, size, max_tries=max_tries)
            self.agent.cur_pos = pos
            next_to = False
            for obj in self.obj_instances.values():
                if obj.check_rel_state(self, self.agent, 'nextto'):
                    next_to = True

        self.agent.cur_pos = pos

        if rand_dir:
            self.agent.dir = self._rand_int(0, 4)

        return pos

    def agent_sees(self, x, y):
        """
        Check if a non-empty grid position is visible to the agent
        """

        coordinates = self.agent.relative_coords(x, y)
        if coordinates is None:
            return False
        vx, vy = coordinates

        obs = self.gen_obs()
        obs_grid, _ = Grid.decode(obs['image'])
        obs_cell = obs_grid.get(vx, vy)
        world_cell = self.grid.get(x, y)

        # TODO: change this to work if isintance(obs_cell, list)
        return obs_cell is not None and obs_cell.type == world_cell.type

    def step(self, action):
        # keep track of last action
        if self.mode == 'human':
            self.last_action = action
        else:
            self.last_action = self.actions(action)

        self.step_count += 1
        self.action_done = True

        # Get the position and contents in front of the agent
        fwd_pos = self.agent.front_pos
        fwd_cell = self.grid.get(*fwd_pos)

        # Rotate left
        if action == self.actions.left:
            self.agent.dir -= 1
            if self.agent.dir < 0:
                self.agent.dir += 4

        # Rotate right
        elif action == self.actions.right:
            self.agent.dir = (self.agent.dir + 1) % 4

        # Move forward
        elif action == self.actions.forward:
            if isinstance(fwd_cell, list):
                can_overlap = True
                obj_types = [obj.type for obj in fwd_cell]
                # TODO: change door
                if 'door' in obj_types:
                    can_overlap = True
                else:
                    for obj in fwd_cell:
                        if not obj.can_overlap:
                            can_overlap = False
                            break
                if can_overlap:
                    self.agent.cur_pos = fwd_pos
                else:
                    self.action_done = False
            else:
                if fwd_cell is None or fwd_cell.can_overlap:
                    self.agent.cur_pos = fwd_pos
                else:
                    self.action_done = False
                if fwd_cell is not None and fwd_cell.type == 'goal':
                    done = True
                    reward = self._reward()
                # if fwd_cell is not None and fwd_cell.type == 'lava':
                #     done = True

        # Choose an object to interact with
        # elif action == self.actions.done:
        #     self.action_done = False
        #     # pass
        else:
            if self.mode == 'human':
                self.last_action = None
                if action == 'choose':
                    if fwd_cell is None and self.agent.carrying == []:
                        print("No reachable objects")
                    else:
                        # get all reachable objects
                        print('Reachable objects')
                        choices = []
                        if isinstance(fwd_cell, list):
                            for obj in fwd_cell:
                                choices.append(obj)
                        elif fwd_cell:
                            choices = [fwd_cell]

                        if self.agent.carrying:
                            choices += self.agent.carrying

                        text = ""
                        for i in range(len(choices)):
                            text += "{}) {} \n".format(i, choices[i].name)
                        obj = input("Choose one of the following objects: \n{}".format(text))
                        obj = choices[int(obj)]
                        assert obj is not None, "No object chosen"

                        actions = []
                        for action in self.agent.actions:
                            if self.agent.actions[action].can(obj):
                                actions.append(action)

                        if len(actions) == 0:
                            print("No actions available")
                        else:
                            text = ""
                            for i in range(len(actions)):
                                text += "{}) {} \n".format(i, actions[i])

                            action = int(input("Choose one of the following actions: \n{}".format(text)))
                            action = actions[action] # action key
                            self.agent.actions[action].do(obj) # perform action

                            self.last_action = self.actions['{}/{}'.format(obj.name, action)]
                # Done action (not used by default)
                else:
                    assert False, "unknown action {}".format(action)
            else:
                # TODO: check that this works
                obj_action = self.actions(action).name.split('/') # list: [obj, action]
                # print("Chosen object: {}".format(obj_action[0]))
                # print("Chosen action: {}".format(obj_action[seed 0_2]))

                # try to perform action
                obj = self.obj_instances[obj_action[0]] # assert obj.name == obj_action[0]
                if self.agent.actions[obj_action[1]].can(obj):
                    self.agent.actions[obj_action[1]].do(obj)
                else:
                    self.action_done = False

                if self.step_count >= self.max_steps:
                    done = True

        reward = self._reward()
        done = self._end_conditions()
        obs = self.gen_obs()
        return obs, reward, done, {}

    def _end_conditions(self):
        print('no end conditions')
        return False

    def gen_obs_grid(self):
        """
        Generate the sub-grid observed by the agent.
        This method also outputs a visibility mask telling us which grid
        cells the agent can actually see.
        """

        topX, topY, botX, botY = self.agent.get_view_exts()

        grid = self.grid.slice(topX, topY, self.agent.view_size, self.agent.view_size)

        for i in range(self.agent.dir + 1):
            grid = grid.rotate_left()

        # Process occluders and visibility
        # Note that this incurs some performance cost
        if not self.see_through_walls:
            vis_mask = grid.process_vis(agent_pos=(self.agent.view_size // 2 , self.agent.view_size - 1))
        else:
            vis_mask = np.ones(shape=(grid.width, grid.height), dtype=bool)

        # Make it so the agent sees what it's carrying
        # We do this by placing the carried object at the agent's position
        # in the agent's partially observable view
        agent_pos = grid.width // 2, grid.height - 1
        # TODO: commented out below. otherwise, there is error with multiroom when you carry an object through door
        if self.agent.carrying:
            grid.set(*agent_pos, self.agent.carrying)
        else:
            grid.set(*agent_pos, None)

        return grid, vis_mask

    def gen_obs(self):
        """
        Generate the agent's view (partially observable, low-resolution encoding)
        """

        grid, vis_mask = self.gen_obs_grid()

        # Encode the partially observable view into a numpy array
        image = grid.encode(vis_mask)

        assert hasattr(self, 'mission'), "environments must define a textual mission string"

        # Observations are dictionaries containing:
        # - an image (partially observable view of the environment)
        # - the agent's direction/orientation (acting as a compass)
        # - a textual mission string (instructions for the agent)
        obs = {
            'image': image,
            'direction': self.agent.dir,
            'mission': self.mission
        }

        return obs

    def get_obs_render(self, obs, tile_size=TILE_PIXELS//2):
        """
        Render an agent observation for visualization
        """

        grid, vis_mask = Grid.decode(obs)

        # Render the whole grid
        img = grid.render(
            tile_size,
            agent_pos=(self.agent.view_size // 2, self.agent.view_size - 1),
            agent_dir=3,
            highlight_mask=vis_mask
        )

        return img

    def render(self, mode='human', close=False, highlight=True, tile_size=TILE_PIXELS):
        """
        Render the whole-grid human view
        """

        if close:
            if self.window:
                self.window.close()
            return

        if mode == 'human' and not self.window:
            import gym_minigrid.window
            self.window = gym_minigrid.window.Window('gym_minigrid')
            self.window.show(block=False)

        if self.window:
            self.window.set_inventory(self)

        # Compute which cells are visible to the agent
        _, vis_mask = self.gen_obs_grid()

        # Compute the world coordinates of the bottom-left corner
        # of the agent's view area
        f_vec = self.agent.dir_vec
        r_vec = self.agent.right_vec
        top_left = self.agent.cur_pos + f_vec * (self.agent.view_size-1) - r_vec * (self.agent.view_size // 2)

        # Mask of which cells to highlight
        highlight_mask = np.zeros(shape=(self.width, self.height), dtype=bool)

        # For each cell in the visibility mask
        for vis_j in range(0, self.agent.view_size):
            for vis_i in range(0, self.agent.view_size):
                # If this cell is not visible, don't highlight it
                if not vis_mask[vis_i, vis_j]:
                    continue

                # Compute the world coordinates of this cell
                abs_i, abs_j = top_left - (f_vec * vis_j) + (r_vec * vis_i)

                if abs_i < 0 or abs_i >= self.width:
                    continue
                if abs_j < 0 or abs_j >= self.height:
                    continue

                # Mark this cell to be highlighted
                highlight_mask[abs_i, abs_j] = True

        # Render the whole grid
        img = self.grid.render(
            tile_size,
            self.agent.cur_pos,
            self.agent.dir,
            highlight_mask=highlight_mask if highlight else None
        )

        if mode == 'human':
            self.window.set_caption(self.mission)
            self.window.show_img(img)

        return img

    def close(self):
        if self.window:
            self.window.close()
        return
